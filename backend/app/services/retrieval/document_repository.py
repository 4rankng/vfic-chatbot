"""Memory match and hybrid document retrieval for the agent read surface.

The knowledge path combines vector retrieval with a small lexical supplement
for exact names, places, and times. Both arms run concurrently; a single-arm
failure degrades to the survivor instead of aborting the turn.

NO business logic, NO LLM/embedder calls — callers compute the embedding (a
graph-layer concern) and hand the repo a vector literal. Methods return
SQLAlchemy Row lists/scalars exactly as the inline ``db.execute(...).all()``
calls did.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBEDDING_DIM, get_settings
from app.shared.domain.text import normalize_vietnamese_text
from app.services.retrieval.fusion import reciprocal_rank_fuse

logger = logging.getLogger(__name__)

# One-shot guard: a persistent embedding-dimension mismatch is logged once per
# process instead of on every retrieval query.
_ann_dim_mismatch_warned = False


class DocumentRepository:
    """Read-only memory + document-chunk queries backing the agent's tools."""

    # Cosine similarity floor: vector results below this are treated as noise.
    # Chosen so that even moderately relevant chunks (>= 0.30) pass while
    # near-orthogonal embeddings (random topic drift) are excluded.
    SIMILARITY_FLOOR = 0.30

    _LEXICAL_STOPWORDS = {
        "anh",
        "ban",
        "bao",
        "ca",
        "cac",
        "cho",
        "co",
        "cua",
        "di",
        "diem",
        "don",
        "duoc",
        "gio",
        "hay",
        "hoi",
        "khong",
        "la",
        "luc",
        "may",
        "minh",
        "nao",
        "noi",
        "o",
        "toi",
        "trong",
        "tuyen",
        "va",
        "ve",
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Per-call degradation flag (read by callers after match_documents to
        # stamp the reason into stage_timings). Reset at the start of every
        # match_documents call; None when no degradation occurred.
        self.last_match_degraded: str | None = None

    @staticmethod
    def _ann_enabled() -> bool:
        global _ann_dim_mismatch_warned
        s = get_settings()
        if not s.rag_ann_enabled:
            return False
        if s.embedding_dim != EMBEDDING_DIM:
            # The pgvector index is a fixed halfvec(EMBEDDING_DIM) HNSW; querying
            # it with a different-width vector would fail or return garbage. Warn
            # once and fall back to exact search instead of failing the turn.
            if not _ann_dim_mismatch_warned:
                logger.warning(
                    "ANN retrieval disabled: configured embedding_dim=%d does not "
                    "match the pgvector vector(%d)/halfvec(%d) index; falling back to "
                    "exact search. Re-index with matching-dimension embeddings to "
                    "re-enable ANN.",
                    s.embedding_dim,
                    EMBEDDING_DIM,
                    EMBEDDING_DIM,
                )
                _ann_dim_mismatch_warned = True
            return False
        return True

    @staticmethod
    def _chunk_visibility(project_clause: str) -> str:
        """Shared WHERE predicate for chunk-scoping (vector + lexical paths).

        Extracted so both queries stay in sync when visibility rules change.
        The FAQ repository reuses it for the same reason.
        """
        return (
            "d.status NOT IN ('ARCHIVED', 'FAILED') "
            "AND c.embedding IS NOT NULL "
            "AND ("
            "  (p.category_authority_started IS TRUE "
            "   AND c.category_revision_id IS NOT NULL AND EXISTS ("
            "    SELECT 1 FROM knowledge_categories kc "
            "    WHERE kc.project_id = p.id AND kc.active_revision_id = c.category_revision_id"
            "  )) "
            "  OR (c.category_revision_id IS NULL AND c.kb_version_id = p.active_kb_version_id "
            "      AND p.category_authority_started IS FALSE) "
            "  OR (c.chunk_type = 'direct_context' "
            "      AND p.knowledge_base_id IS NOT NULL "
            "      AND EXISTS (SELECT 1 FROM knowledge_bases kb "
            "                  WHERE kb.id = p.knowledge_base_id "
            "                    AND kb.mode = 'DIRECT_CONTEXT'))"
            ") "
            "AND (CAST(:filter AS jsonb) = '{}'::jsonb OR c.metadata @> CAST(:filter AS jsonb)) "
            f"{project_clause} "
            "AND ("
            "  c.metadata #>> '{document_metadata,schema_version}' IS NULL "
            "  OR ("
            "    COALESCE(c.metadata #>> '{document_metadata,effective_from}', '0001-01-01')::date <= CURRENT_DATE "
            "    AND (c.metadata #>> '{document_metadata,effective_to}' IS NULL "
            "         OR (c.metadata #>> '{document_metadata,effective_to}')::date >= CURRENT_DATE)"
            "  )"
            ")"
        )

    async def match_memories(self, emb: str, top_k: int, filter_json: str) -> list:
        """Top-k memory rows for a chat.

        Both arms bind the query as ``halfvec(3072)`` so the distance
        expression matches the ``memories_embedding_halfvec_hnsw_idx``
        expression index (0016) and the HNSW index can serve them; a
        ``vector`` argument would select the exact-compute plan and the
        index would stay dead weight. The chat-scoped arm queries
        ``memories`` directly; the general arm goes through the
        ``match_memories`` SQL function, which orders by the same cast.
        """
        try:
            filter_obj = json.loads(filter_json or "{}")
        except json.JSONDecodeError:
            filter_obj = {}
        chat_id = filter_obj.get("chat_id")
        if isinstance(chat_id, str) and set(filter_obj) <= {"chat_id"}:
            # Cast to halfvec(3072) — not vector — so the query expression
            # matches the memories_embedding_halfvec_hnsw_idx index expression
            # and the HNSW index can actually serve this path.
            return (
                await self.db.execute(
                    text(
                        "SELECT id, content, metadata, "
                        "       1 - (embedding::halfvec(3072) "
                        "            <=> CAST(:emb AS halfvec(3072))) AS similarity "
                        "FROM memories "
                        "WHERE chat_id = :chat_id AND embedding IS NOT NULL "
                        "ORDER BY embedding::halfvec(3072) "
                        "         <=> CAST(:emb AS halfvec(3072)) "
                        "LIMIT :k"
                    ),
                    {"emb": emb, "k": top_k, "chat_id": chat_id},
                )
            ).all()
        # ``halfvec(3072)``, not ``vector``: this is the only overload of
        # ``match_memories`` (0057 dropped the vector one), and its ORDER BY
        # is ``embedding::halfvec(3072) <=> <query>`` — the exact expression
        # the HNSW index is built on. Mirrors the fast path above.
        return (
            await self.db.execute(
                text(
                    "SELECT content, similarity FROM match_memories("
                    "CAST(:emb AS halfvec(3072)), :k, CAST(:filter AS jsonb))"
                ),
                {"emb": emb, "k": top_k, "filter": filter_json},
            )
        ).all()

    @classmethod
    def _lexical_terms(cls, query: str | None) -> list[str]:
        q = normalize_vietnamese_text(query or "")
        terms = [
            term for term in q.split() if len(term) >= 3 and term not in cls._LEXICAL_STOPWORDS
        ]
        seen: set[str] = set()
        return [term for term in terms if not (term in seen or seen.add(term))]

    async def _match_document_vector_rows(
        self,
        *,
        emb: str,
        top_k: int,
        filter_json: str,
        project_clause: str,
        project_ids: list[str] | None,
    ) -> list:
        params: dict[str, object] = {"emb": emb, "k": top_k, "filter": filter_json}
        if project_ids:
            params["pids"] = project_ids
        s = get_settings()
        if self._ann_enabled():
            # The exact vector distance is computed ONCE per candidate row (in
            # the inner SELECT aliased ``dist``) and referenced by the floor
            # predicate and the ORDER BY — previously the same 3072-dim
            # expression ran three times per row. Candidate selection in
            # ``ann_candidates`` keeps the halfvec cast that matches the 0016
            # HNSW index expression.
            # Filtering/ordering on ``dist`` preserves the previous rows and
            # order. The sort key was the distance in both forms. For the
            # floor: over the decision band (cosine distance 0.5–1.0) the old
            # ``1 - dist`` subtraction is exact (Sterbenz lemma), and the
            # sub-ulp gap between the double 0.7 and the exact 1 - 0.3
            # literal contains no further double, so ``dist <= 1 - 0.30``
            # accepts precisely the same rows (verified by an exhaustive
            # double sweep). If SIMILARITY_FLOOR changes, re-derive this
            # boundary rather than assuming it carries over.
            vector_sql = (
                "WITH ann_candidates AS ("
                "  SELECT c.id "
                "  FROM knowledge_chunks c "
                "  JOIN knowledge_documents d ON d.id = c.document_id "
                "  JOIN projects p ON p.id = d.project_id "
                "  WHERE " + self._chunk_visibility(project_clause) + " "
                "  ORDER BY c.embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072)) "
                "  LIMIT :candidate_k"
                ") "
                "SELECT id, content, source_quote, summary, metadata, "
                "       line_start, line_end, section_path, source_file, "
                "       1 - dist AS similarity "
                "FROM ("
                "  SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                "         c.line_start, c.line_end, c.section_path, "
                "         ktf.filename AS source_file, "
                "         (c.embedding <=> CAST(:emb AS vector)) AS dist "
                "  FROM ann_candidates ac "
                "  JOIN knowledge_chunks c ON c.id = ac.id "
                "  LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id"
                ") scored "
                "WHERE dist <= :max_dist "
                "ORDER BY dist "
                "LIMIT :k"
            )
            params = {
                **params,
                "max_dist": 1 - self.SIMILARITY_FLOOR,
                "candidate_k": max(int(s.rag_ann_candidates), top_k),
            }
        else:
            vector_sql = (
                "SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                "       c.line_start, c.line_end, c.section_path, ktf.filename AS source_file, "
                "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                "FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON d.id = c.document_id "
                "JOIN projects p ON p.id = d.project_id "
                "LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id "
                "WHERE " + self._chunk_visibility(project_clause) + " "
                "  AND 1 - (c.embedding <=> CAST(:emb AS vector)) >= :floor "
                "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                "LIMIT :k"
            )
            params = {**params, "floor": self.SIMILARITY_FLOOR}
        return (await self.db.execute(text(vector_sql), params)).all()

    async def _match_document_lexical_rows(
        self,
        *,
        top_k: int,
        filter_json: str,
        project_clause: str,
        project_ids: list[str] | None,
        terms: list[str],
        emb: str,
    ) -> list:
        lexical_terms = terms[:8]
        term_predicates = [
            f"c.search_text ILIKE :term_like_{i}" for i, _term in enumerate(lexical_terms)
        ]
        lexical_prefilter = " OR ".join(term_predicates) or "false"
        params: dict[str, object] = {
            "emb": emb,
            "k": top_k,
            "filter": filter_json,
            "terms": lexical_terms,
            **{f"term_like_{i}": f"%{term}%" for i, term in enumerate(lexical_terms)},
        }
        if project_ids:
            params["pids"] = project_ids
        return (
            await self.db.execute(
                text(
                    "WITH haystack AS ("
                    "  SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                    "         c.line_start, c.line_end, c.section_path, ktf.filename AS source_file, "
                    "         COALESCE(c.search_text, public.normalize_search_text("
                    "           COALESCE(c.content, '') || ' ' || COALESCE(c.source_quote, '') || ' ' || COALESCE(c.summary, '')"
                    "         )) AS searchable "
                    "  FROM knowledge_chunks c "
                    "  JOIN knowledge_documents d ON d.id = c.document_id "
                    "  JOIN projects p ON p.id = d.project_id "
                    "  LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id "
                    "  WHERE " + self._chunk_visibility(project_clause) + " "
                    "    AND (c.search_text IS NULL OR " + lexical_prefilter + ") "
                    "), scored AS ("
                    "  SELECT id, content, source_quote, summary, metadata, "
                    "         line_start, line_end, section_path, source_file, "
                    "         (SELECT count(*) FROM unnest(CAST(:terms AS text[])) AS term(value) "
                    "          WHERE position(term.value IN searchable) > 0) AS lexical_hits "
                    "  FROM haystack"
                    ") "
                    "SELECT id, content, source_quote, summary, metadata, "
                    "       line_start, line_end, section_path, source_file, "
                    "  lexical_hits::double precision "
                    "  / GREATEST(CARDINALITY(CAST(:terms AS text[]))::double precision, 1.0) AS similarity "
                    "FROM scored "
                    "WHERE lexical_hits >= LEAST(2, CARDINALITY(CAST(:terms AS text[]))) "
                    "ORDER BY lexical_hits DESC "
                    "LIMIT :k"
                ),
                params,
            )
        ).all()

    async def match_documents(
        self,
        emb: str,
        top_k: int,
        filter_json: str,
        *,
        project_ids: list[str] | None = None,
        query_text: str | None = None,
    ) -> list:
        """Top-k usable knowledge rows directly from chunks + documents.

        The old path called the ``documents`` compatibility view. Migration 0010 removes
        that view, so the app now owns the explicit query and returns namespaced
        metadata for citations/effective-date handling.

        Retrieval arms run CONCURRENTLY (Tech-Lead Directive §4): vector + lexical
        execute via ``asyncio.gather`` so the wall-clock cost is max(vector, lexical),
        not sum. If the vector arm raises, the turn degrades gracefully to
        lexical-only (the directive's "if vector search times out, use lexical +
        structured results"). The arms are not individually time-boxed here: turn
        time-boxing is the queue-level deadline-at-epoch only (the per-stage
        retrieval/rerank budgets were removed with ``app/services/chatbot/``).

        Degradation is observable: the caller can read ``self.last_match_degraded``
        after this returns to stamp the reason into ``stage_timings`` (see runner.py).
        """
        project_clause = ""
        if project_ids:
            project_clause = "AND d.project_id = ANY(CAST(:pids AS uuid[]))"
        terms = self._lexical_terms(query_text)
        # Reset the per-call degradation flag (callers read it after return).
        self.last_match_degraded: str | None = None

        # No lexical terms → vector-only path (legacy fast exit, no gather overhead).
        if not terms:
            vector_rows = await self._match_document_vector_rows(
                emb=emb,
                top_k=top_k,
                filter_json=filter_json,
                project_clause=project_clause,
                project_ids=project_ids,
            )
            return self._finalize_retrieval([], vector_rows, top_k, query_text or "")

        # Run both arms concurrently so a slow vector arm cannot gate the lexical
        # arm. ``return_exceptions=True`` lets the surviving arm win on a
        # single-arm failure rather than propagating the error up to abort the
        # turn.
        vector_task = asyncio.ensure_future(
            self._match_document_vector_rows(
                emb=emb,
                top_k=top_k,
                filter_json=filter_json,
                project_clause=project_clause,
                project_ids=project_ids,
            )
        )
        lexical_task = asyncio.ensure_future(
            self._match_document_lexical_rows(
                emb=emb,
                top_k=top_k,
                filter_json=filter_json,
                project_clause=project_clause,
                project_ids=project_ids,
                terms=terms,
            )
        )
        results = await asyncio.gather(vector_task, lexical_task, return_exceptions=True)
        vector_result, lexical_result = results

        vector_rows: list = []
        lexical_rows: list = []
        if isinstance(vector_result, Exception):
            # Vector arm failed (timeout or error). Degrade to lexical-only.
            self.last_match_degraded = "retrieval_vector_failed"
            logger.warning(
                "match_documents vector arm failed; degrading to lexical-only",
                exc_info=vector_result,
            )
        else:
            vector_rows = vector_result
        if isinstance(lexical_result, Exception):
            # Lexical arm failed. If vector also failed, we have nothing — return []
            # and let the agent answer from prompt context (the grounding policy
            # handles empty evidence). Otherwise vector-only is fine.
            if not vector_rows:
                self.last_match_degraded = "retrieval_both_arms_failed"
                return []
            self.last_match_degraded = self.last_match_degraded or "retrieval_lexical_failed"
            logger.warning(
                "match_documents lexical arm failed; using vector-only",
                exc_info=lexical_result,
            )
        else:
            lexical_rows = lexical_result

        return self._finalize_retrieval(lexical_rows, vector_rows, top_k, query_text or "")

    def _finalize_retrieval(
        self, lexical_rows: list, vector_rows: list, top_k: int, query_text: str
    ) -> list:
        """Fuse + rerank the two arms. Handles single-arm fallbacks."""
        if not lexical_rows and not vector_rows:
            return []
        if not lexical_rows:
            # Vector-only (no lexical terms, or lexical arm failed).
            from app.services.retrieval.reranker import rerank_if_enabled

            return rerank_if_enabled(vector_rows, query_text=query_text)
        if not vector_rows:
            # Lexical-only fallback (vector arm timed out / failed).
            from app.services.retrieval.reranker import rerank_if_enabled

            return rerank_if_enabled(lexical_rows, query_text=query_text)
        merged = reciprocal_rank_fuse(
            vector_rows,
            lexical_rows,
            top_k=top_k,
            rank_constant=get_settings().rag_rrf_rank_constant,
        )
        logger.debug(
            "match_documents RRF fused: %d rows (%d lexical, %d vector, top_k=%d)",
            len(merged),
            len(lexical_rows),
            len(vector_rows),
            top_k,
        )
        from app.services.retrieval.reranker import rerank_if_enabled

        return rerank_if_enabled(merged, query_text=query_text)
