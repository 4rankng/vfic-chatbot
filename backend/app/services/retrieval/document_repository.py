"""Memory match and document retrieval for the agent read surface.

The knowledge path is semantic (vector) retrieval only. A lexical supplement
(terms + stopwords + RRF fusion) used to run alongside it; it was removed
after a diacritic-folded substring collision ("chuyen" từ "chuyên ca" matching
"chuyên cần") ranked unrelated allowance chunks above the relevant shift
chunks and the bot answered from the wrong evidence.

NO business logic, NO LLM/embedder calls — callers compute the embedding (a
graph-layer concern) and hand the repo a vector literal. Methods return
SQLAlchemy Row lists/scalars exactly as the inline ``db.execute(...).all()``
calls did.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBEDDING_DIM, get_settings

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
        """Shared WHERE predicate for chunk-scoping (the vector path).

        Extracted so both queries stay in sync when visibility rules change.
        The FAQ repository reuses it for the same reason.
        """
        return (
            "p.is_active IS TRUE "
            "AND p.knowledge_base_id IS NOT NULL "
            "AND d.status NOT IN ('ARCHIVED', 'FAILED') "
            "AND c.embedding IS NOT NULL "
            "AND (c.project_id IS NULL OR c.project_id = p.id) "
            "AND ("
            "  (p.category_authority_started IS TRUE "
            "   AND c.category_revision_id IS NOT NULL AND EXISTS ("
            "    SELECT 1 FROM knowledge_categories kc "
            "    JOIN knowledge_category_revisions kr ON kr.category_id = kc.id "
            "    WHERE kc.project_id = p.id AND kc.active_revision_id = kr.id "
            "      AND kr.id = c.category_revision_id "
            "      AND d.category_revision_id = kr.id"
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
            return list(
                (
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
            )
        # ``halfvec(3072)``, not ``vector``: this is the only overload of
        # ``match_memories`` (0057 dropped the vector one), and its ORDER BY
        # is ``embedding::halfvec(3072) <=> <query>`` — the exact expression
        # the HNSW index is built on. Mirrors the fast path above.
        return list(
            (
                await self.db.execute(
                    text(
                        "SELECT content, similarity FROM match_memories("
                        "CAST(:emb AS halfvec(3072)), :k, CAST(:filter AS jsonb))"
                    ),
                    {"emb": emb, "k": top_k, "filter": filter_json},
                )
            ).all()
        )

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
                "  SELECT c.id, p.name AS project_name, p.slug AS project_slug, "
                "         d.file_name AS document_file "
                "  FROM knowledge_chunks c "
                "  JOIN knowledge_documents d ON d.id = c.document_id "
                "  JOIN projects p ON p.id = d.project_id "
                "  WHERE " + self._chunk_visibility(project_clause) + " "
                "  ORDER BY c.embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072)) "
                "  LIMIT :candidate_k"
                ") "
                "SELECT id, content, source_quote, summary, metadata, "
                "       line_start, line_end, section_path, source_file, "
                "       project_name, project_slug, category, "
                "       1 - dist AS similarity "
                "FROM ("
                "  SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                "         c.line_start, c.line_end, c.section_path, "
                "         COALESCE(ktf.filename, ac.document_file) AS source_file, "
                "         ac.project_name, ac.project_slug, c.category, "
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
                "       c.line_start, c.line_end, c.section_path, "
                "       COALESCE(ktf.filename, d.file_name) AS source_file, "
                "       p.name AS project_name, p.slug AS project_slug, c.category, "
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
        return list((await self.db.execute(text(vector_sql), params)).all())

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

        Semantic (vector) retrieval only. The former lexical arm ranked chunks
        by diacritic-folded substring hits, which let "chuyen" (từ "chuyên ca")
        pull in "chuyên cần" allowance chunks and bury the relevant shift
        chunks — the LLM then answered from the wrong evidence. Keyword
        pre-ranking is gone; ranking is the embedder's (+ the optional
        reranker's) job, and the LLM decides what the answer is.

        Degradation is observable: the caller can read ``self.last_match_degraded``
        after this returns to stamp the reason into ``stage_timings`` (see runner.py).
        """
        # None is an internal unrestricted read; an explicitly empty channel
        # or project scope must never turn into a deployment-wide query.
        self.last_match_degraded = None
        if project_ids == []:
            return []
        project_clause = ""
        if project_ids:
            project_clause = "AND d.project_id = ANY(CAST(:pids AS uuid[]))"
        # Reset the per-call degradation flag (callers read it after return).
        self.last_match_degraded: str | None = None
        try:
            vector_rows = await self._match_document_vector_rows(
                emb=emb,
                top_k=top_k,
                filter_json=filter_json,
                project_clause=project_clause,
                project_ids=project_ids,
            )
        except Exception:
            # Vector arm failed (timeout or error). Return nothing and let the
            # grounding policy / prefetch-miss paths handle the empty evidence
            # instead of answering from stale context.
            self.last_match_degraded = "retrieval_vector_failed"
            logger.warning("match_documents vector arm failed", exc_info=True)
            return []
        return self._finalize_retrieval(vector_rows, top_k, query_text or "")

    def _finalize_retrieval(
        self, vector_rows: list, top_k: int, query_text: str
    ) -> list:
        """Rerank the vector rows (reranker disabled by default → pass-through)."""
        if not vector_rows:
            return []
        from app.services.retrieval.reranker import rerank_if_enabled

        return list(rerank_if_enabled(vector_rows, query_text=query_text))
