"""Retrieval data-access for the agent layer.

Ports of the queries that ``app/graph/tools.py`` and ``app/graph/context.py``
previously ran inline, so the graph layer no longer owns ``text()`` SQL. The
knowledge path combines vector retrieval with a small lexical supplement for
exact names, places, and times.

NO business logic, NO LLM/embedder calls — callers compute the embedding (a
graph-layer concern) and hand the repo a vector literal. Methods return SQLAlchemy
Row lists/scalars exactly as the inline ``db.execute(...).all()`` calls did.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBEDDING_DIM, get_settings
from app.core.text import normalize_vietnamese_text
from app.services.retrieval.fusion import reciprocal_rank_fuse

logger = logging.getLogger(__name__)

# One-shot guard: a persistent embedding-dimension mismatch is logged once per
# process instead of on every retrieval query.
_ann_dim_mismatch_warned = False


class RetrievalRepository:
    """Read-only retrieval queries backing the agent's tools + prompt assembly."""

    # Cosine similarity floor: vector results below this are treated as noise.
    # Chosen so that even moderately relevant chunks (>= 0.30) pass while
    # near-orthogonal embeddings (random topic drift) are excluded.
    SIMILARITY_FLOOR = 0.30
    FAQ_SIMILARITY_FLOOR = 0.70

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
        """
        return (
            "d.status NOT IN ('ARCHIVED', 'FAILED') "
            "AND c.embedding IS NOT NULL "
            "AND c.kb_version_id = p.active_kb_version_id "
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
        """Top-k memory rows for a chat (``match_memories`` SQL function)."""
        try:
            filter_obj = json.loads(filter_json or "{}")
        except json.JSONDecodeError:
            filter_obj = {}
        chat_id = filter_obj.get("chat_id")
        if isinstance(chat_id, str) and set(filter_obj) <= {"chat_id"}:
            return (
                await self.db.execute(
                    text(
                        "SELECT id, content, metadata, "
                        "       1 - (embedding <=> CAST(:emb AS vector)) AS similarity "
                        "FROM memories "
                        "WHERE chat_id = :chat_id AND embedding IS NOT NULL "
                        "ORDER BY embedding <=> CAST(:emb AS vector) "
                        "LIMIT :k"
                    ),
                    {"emb": emb, "k": top_k, "chat_id": chat_id},
                )
            ).all()
        return (
            await self.db.execute(
                text(
                    "SELECT content, similarity FROM match_memories("
                    "CAST(:emb AS vector), :k, CAST(:filter AS jsonb))"
                ),
                {"emb": emb, "k": top_k, "filter": filter_json},
            )
        ).all()

    @classmethod
    def _lexical_terms(cls, query: str | None) -> list[str]:
        q = cls._normalize_text(query or "")
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
                "SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                "       c.line_start, c.line_end, c.section_path, ktf.filename AS source_file, "
                "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                "FROM ann_candidates ac "
                "JOIN knowledge_chunks c ON c.id = ac.id "
                "LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id "
                "WHERE 1 - (c.embedding <=> CAST(:emb AS vector)) >= :floor "
                "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                "LIMIT :k"
            )
            params = {
                **params,
                "floor": self.SIMILARITY_FLOOR,
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
        deadline=None,
    ) -> list:
        """Top-k usable knowledge rows directly from chunks + documents.

        The old path called the ``documents`` compatibility view. Migration 0010 removes
        that view, so the app now owns the explicit query and returns namespaced
        metadata for citations/effective-date handling.

        Retrieval arms run CONCURRENTLY (Tech-Lead Directive §4): vector + lexical
        execute via ``asyncio.gather`` so the wall-clock cost is max(vector, lexical),
        not sum. If the vector arm raises or exceeds its budget, the turn degrades
        gracefully to lexical-only (the directive's "if vector search times out, use
        lexical + structured results"). ``deadline`` is an optional
        ``app.services.chatbot.deadlines.TurnDeadline``; when None (tests / legacy callers) the
        arms run unbounded, matching pre-existing behaviour.

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
            vector_rows = await self._run_vector_arm(
                emb, top_k, filter_json, project_clause, project_ids, deadline
            )
            return self._finalize_retrieval([], vector_rows, top_k, query_text or "")

        # Run both arms concurrently. Each arm is individually time-boxed against
        # the retrieval budget so a slow vector arm doesn't gate the lexical arm.
        # ``return_exceptions=True`` lets the surviving arm win on a single-arm
        # failure rather than propagating the error up to abort the turn.
        vector_task = asyncio.ensure_future(
            self._run_vector_arm(emb, top_k, filter_json, project_clause, project_ids, deadline)
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

    async def _run_vector_arm(
        self, emb, top_k, filter_json, project_clause, project_ids, deadline
    ) -> list:
        """Vector arm, time-boxed against ``deadline.retrieval`` when set."""
        if deadline is None or deadline.overall <= 0:
            return await self._match_document_vector_rows(
                emb=emb,
                top_k=top_k,
                filter_json=filter_json,
                project_clause=project_clause,
                project_ids=project_ids,
            )
        budget = deadline.budget_for("retrieval")
        if budget is None:
            return await self._match_document_vector_rows(
                emb=emb,
                top_k=top_k,
                filter_json=filter_json,
                project_clause=project_clause,
                project_ids=project_ids,
            )
        try:
            return await asyncio.wait_for(
                self._match_document_vector_rows(
                    emb=emb,
                    top_k=top_k,
                    filter_json=filter_json,
                    project_clause=project_clause,
                    project_ids=project_ids,
                ),
                timeout=budget,
            )
        except TimeoutError:
            # Propagate as a generic exception so gather's return_exceptions
            # buckets it with the error path; the caller degrades to lexical.
            raise

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

    async def match_faq(
        self,
        emb: str,
        top_k: int = 3,
        *,
        filter_json: str = "{}",
        project_ids: list[str] | None = None,
        floor: float | None = None,
    ) -> list:
        """FAQ-first retrieval: scoped to ``category='faq'`` chunks with a higher floor.

        Used by ``search_knowledge`` to prepend canonical FAQ answers before the
        general retrieval pass.  Reuses ``_chunk_visibility`` for status / effective-date /
        project scoping so archived or out-of-date FAQ chunks are excluded automatically.
        """
        if floor is None:
            floor = self.FAQ_SIMILARITY_FLOOR
        project_clause = ""
        params: dict[str, object] = {"emb": emb, "k": top_k, "filter": filter_json}
        if project_ids:
            project_clause = "AND d.project_id = ANY(CAST(:pids AS uuid[]))"
            params["pids"] = project_ids
        rows = (
            await self.db.execute(
                text(
                    "SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                    "       c.questions, c.required_terms, c.forbidden_terms, "
                    "       c.line_start, c.line_end, c.section_path, ktf.filename AS source_file, "
                    "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                    "FROM knowledge_chunks c "
                    "JOIN knowledge_documents d ON d.id = c.document_id "
                    "JOIN projects p ON p.id = d.project_id "
                    "LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id "
                    "WHERE " + self._chunk_visibility(project_clause) + " "
                    "  AND c.category = 'faq' "
                    "  AND 1 - (c.embedding <=> CAST(:emb AS vector)) >= :faq_floor "
                    "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                    "LIMIT :k"
                ),
                {**params, "faq_floor": floor},
            )
        ).all()
        logger.debug(
            "match_faq: %d rows (floor=%.2f, category=faq)",
            len(rows),
            floor,
        )
        return list(rows)

    async def match_faq_lexical(
        self,
        query: str,
        *,
        top_k: int = 5,
        project_ids: list[str] | None = None,
        filter_json: str = "{}",
        threshold: float = 0.30,
    ) -> list:
        """FAQ-scoped trigram retrieval — the lexical/exact arm of the FAQ bypass.

        Uses ``similarity()`` over ``normalize_search_text(search_text)`` so it is
        diacritic- and case-insensitive. Both the stored text and the query are
        normalized in SQL (via ``public.normalize_search_text``) so the two sides
        match exactly. NOTE: wrapping the column in ``normalize_search_text`` means
        this is a sequential scan over the (small, FAQ-scoped) chunk set, NOT the
        ``knowledge_chunks_search_text_trgm_idx`` GIN index (which indexes bare
        ``search_text``); acceptable at FAQ cardinality, revisit only if the FAQ
        corpus grows large. Returns ``questions``/``required_terms``/
        ``forbidden_terms`` so the bypass can run its exact-match and rule tiers
        without a second fetch.
        """
        project_clause = ""
        params: dict[str, object] = {
            "q": query,
            "k": top_k,
            "filter": filter_json,
            "thr": threshold,
        }
        if project_ids:
            project_clause = "AND d.project_id = ANY(CAST(:pids AS uuid[]))"
            params["pids"] = project_ids
        rows = (
            await self.db.execute(
                text(
                    "SELECT c.id, c.questions, c.source_quote, c.summary, c.content, "
                    "       c.metadata, c.required_terms, c.forbidden_terms, "
                    "       similarity(public.normalize_search_text(COALESCE(c.search_text, '')), "
                    "                  public.normalize_search_text(:q)) AS similarity "
                    "FROM knowledge_chunks c "
                    "JOIN knowledge_documents d ON d.id = c.document_id "
                    "JOIN projects p ON p.id = d.project_id "
                    "LEFT JOIN kb_text_files ktf ON ktf.id = c.file_id "
                    "WHERE " + self._chunk_visibility(project_clause) + " "
                    "  AND c.category = 'faq' "
                    "  AND similarity(public.normalize_search_text(COALESCE(c.search_text, '')), "
                    "                 public.normalize_search_text(:q)) >= :thr "
                    "ORDER BY similarity DESC "
                    "LIMIT :k"
                ),
                params,
            )
        ).all()
        logger.debug(
            "match_faq_lexical: %d rows (threshold=%.2f, category=faq)",
            len(rows),
            threshold,
        )
        return list(rows)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return normalize_vietnamese_text(value)

    @classmethod
    def _requested_bus_shifts(cls, question: str) -> list[str | None]:
        # Strip punctuation so "ca ngày, ca đêm" → {"ca", "ngay", "ca", "dem"}
        q = cls._normalize_text(question)
        clean = "".join(c if c.isalnum() or c.isspace() else " " for c in q)
        words = set(clean.split())
        wants_day = {"ca", "ngay"} <= words or {"ca", "sang"} <= words or {"buoi", "sang"} <= words
        wants_night = {"ca", "dem"} <= words
        wants_admin = {"hanh", "chinh"} <= words
        shifts: list[str | None] = []
        if wants_day:
            shifts.append("day")
        if wants_night:
            shifts.append("night")
        if wants_admin:
            shifts.append("admin")
        return shifts or [None]

    async def project_id_by_slug(self, slug: str, *, active_only: bool = False) -> uuid.UUID | None:
        """Resolve a project id from its (unique) slug; optionally require ``is_active``."""
        sql = "SELECT id FROM projects WHERE slug = :s"
        if active_only:
            sql += " AND is_active"
        return (await self.db.execute(text(sql), {"s": slug})).scalar_one_or_none()

    async def list_active_projects(self) -> list:
        """name/slug/summary of active projects (catalog tool)."""
        return (
            await self.db.execute(
                text("SELECT name, slug, summary FROM projects WHERE is_active ORDER BY name")
            )
        ).all()

    async def active_projects_with_card(self) -> list:
        """Active projects for the master-index prompt, including persona overrides."""
        return (
            await self.db.execute(
                text(
                    "SELECT p.name, p.slug, p.summary, p.index_card, "
                    "       pe.name AS persona_name, pe.body_md AS persona_body_md "
                    "FROM projects p "
                    "LEFT JOIN personas pe ON pe.id = p.default_persona_id AND pe.is_active "
                    "WHERE p.is_active "
                    "ORDER BY p.name"
                )
            )
        ).all()

    async def active_persona_body(self) -> str | None:
        """``body_md`` of the single active global persona, or None."""
        return (
            await self.db.execute(
                text("SELECT body_md FROM personas WHERE is_active AND project_id IS NULL LIMIT 1")
            )
        ).scalar_one_or_none()

    async def search_bus_timetable(self, company: str, question: str, limit: int) -> list:
        """Complete route rows matching a bus timetable question.

        ``p_project_slug`` is passed as NULL so the search spans all projects --
        the deployment is single-tenant and the ``company`` filter already scopes
        the rows. Migration 0011 made the SQL fn NULL-tolerant; passing a slug
        here would re-introduce the unreachable-canonical-timetable bug, since
        canonical Markdown is persisted under the frontmatter ``project_slug``
        (e.g. 'lg-display'), not 'vfic'.

        The SQL function ranks one row per stop. For a stop-level query such as
        "Cty TNHH Hào Quang", the initial result can contain only the matching
        stop. The agent needs the complete route, so this method uses the SQL
        function only to identify candidate route groups, then fetches all stops
        for those routes in stop_order. It also calls the function once per
        requested shift so "ca ngày và ca đêm" cannot collapse to one shift.
        """
        candidate_rows: list = []
        candidate_limit = max(limit * 25, 500)
        for shift in self._requested_bus_shifts(question):
            rows = (
                await self.db.execute(
                    text(
                        "SELECT * FROM search_bus_timetable(NULL, :company, :question, :shift, NULL, :limit)"
                    ),
                    {
                        "company": company,
                        "question": question,
                        "shift": shift,
                        "limit": candidate_limit,
                    },
                )
            ).all()
            candidate_rows.extend(rows)

        route_keys: list[dict[str, object]] = []
        seen: set[tuple] = set()
        fallback_rows: list = []
        for row in candidate_rows:
            m = dict(row._mapping)
            if not m.get("stop_name"):
                fallback_rows.append(row)
                continue
            key = (
                m.get("company_name"),
                m.get("route_name"),
                m.get("route_variant") or "",
                m.get("shift") or "",
                m.get("direction") or "",
                m.get("source_page") or "",
                m.get("mode") or "",
            )
            if key in seen:
                continue
            seen.add(key)
            route_keys.append(
                {
                    "company_name": key[0],
                    "route_name": key[1],
                    "route_variant": key[2],
                    "shift": key[3],
                    "direction": key[4],
                    "source_page": key[5],
                    "mode": key[6],
                }
            )
        # Cap after processing ALL shifts so multi-shift queries aren't truncated.
        route_keys = route_keys[:limit]

        # Filter out keys with NULL required fields (would fail JOIN on NULL = NULL).
        route_keys = [k for k in route_keys if k.get("company_name") and k.get("route_name")]
        if not route_keys:
            return fallback_rows

        return (
            await self.db.execute(
                text(
                    """
                    WITH candidate_routes AS (
                      SELECT *
                      FROM jsonb_to_recordset(CAST(:keys AS jsonb)) AS k(
                        company_name text,
                        route_name text,
                        route_variant text,
                        shift text,
                        direction text,
                        source_page text,
                        mode text
                      )
                    )
                    SELECT
                      c.name AS company_name,
                      br.route_name,
                      br.route_variant,
                      br.shift,
                      br.direction,
                      bs.stop_order,
                      bs.stop_name,
                      to_char(bs.scheduled_time, 'HH24:MI') AS scheduled_time,
                      br.area,
                      br.mode,
                      ks.source_name,
                      br.source_page,
                      'complete matched route' AS match_reason,
                      NULL::text AS requested_day_group,
                      NULL::text AS requested_day_label,
                      NULL::text AS availability_code
                    FROM candidate_routes cr
                    JOIN companies c ON c.name = cr.company_name
                    JOIN bus_routes br
                      ON br.company_id = c.id
                     AND br.route_name = cr.route_name
                     AND COALESCE(br.route_variant, '') = COALESCE(cr.route_variant, '')
                     AND COALESCE(br.shift, '') = COALESCE(cr.shift, '')
                     AND COALESCE(br.direction, '') = COALESCE(cr.direction, '')
                     AND COALESCE(br.source_page, '') = COALESCE(cr.source_page, '')
                     AND COALESCE(br.mode, '') = COALESCE(cr.mode, '')
                    JOIN bus_stops bs ON bs.route_id = br.id
                    LEFT JOIN knowledge_sources ks ON ks.id = br.knowledge_source_id
                    ORDER BY
                      array_position(CAST(:route_names AS text[]), br.route_name),
                      CASE br.shift WHEN 'day' THEN 1 WHEN 'admin' THEN 2 WHEN 'night' THEN 3 ELSE 4 END,
                      br.direction,
                      bs.stop_order
                    """
                ),
                {
                    "keys": json.dumps(route_keys, ensure_ascii=False),
                    "route_names": [str(k["route_name"]) for k in route_keys],
                },
            )
        ).all()

    async def job_features_for_project(self, project_id: uuid.UUID) -> list:
        """A project's active worker features in catalog display order.

        Filtered to ``is_active`` catalog rows so disabled criteria (migration 0009) are
        hidden from the agent tool and readiness gauge without re-extraction.
        """
        return (
            await self.db.execute(
                text(
                    "SELECT jfv.value_text, jfv.value_json, jfv.is_highlight, jfv.is_missing, "
                    "       jfv.needs_clarification, jfv.evidence_text, "
                    "       wfc.name_vi, wfc.feature_key "
                    "FROM job_feature_values jfv "
                    "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                    "WHERE jfv.project_id = :pid AND wfc.is_active = true "
                    "ORDER BY jfv.display_priority ASC, wfc.default_importance_score DESC"
                ),
                {"pid": str(project_id)},
            )
        ).all()

    async def match_jobs_for_lead(
        self, chat_id: str, *, top_k: int = 5, province: str | None = None
    ) -> list:
        """Structured Job↔Lead recommendation (Phase 2).

        Loads the lead by ``chat_id`` (zalo_id), builds a :class:`LeadProfile`,
        and runs the two-stage ranker (:class:`RecommendationRepository`).
        Returns :class:`ScoredJob` objects (job + score + matched reasons).
        Deprecated compatibility method. New callers should use
        :meth:`recommend_jobs_for_lead`, which keeps no-match, missing-profile,
        and unavailable states distinct.
        """
        from app.services.lead.repository import LeadRepository
        from app.services.recommendation import RecommendationRepository, LeadProfile

        try:
            lead = await LeadRepository(self.db).by_zalo_id(chat_id)
            profile = LeadProfile.from_lead(lead)
            if not profile.has_any_signal:
                return []
            return await RecommendationRepository(self.db).match_jobs(
                profile, top_k=top_k, province=province
            )
        except Exception:
            logger.warning("match_jobs_for_lead failed for chat_id=%s", chat_id, exc_info=True)
            return []

    async def recommend_jobs_for_lead(
        self, chat_id: str, *, top_k: int = 5, province: str | None = None
    ):
        """Return a typed profile-based job recommendation outcome."""
        from app.services.lead.repository import LeadRepository
        from app.services.recommendation import LeadJobRecommendation, LeadProfile, RecommendationRepository

        try:
            lead = await LeadRepository(self.db).by_zalo_id(chat_id)
            profile = LeadProfile.from_lead(lead)
        except Exception:
            logger.warning("lead lookup failed for chat_id=%s", chat_id, exc_info=True)
            return LeadJobRecommendation("unavailable")
        if not profile.has_any_signal:
            return LeadJobRecommendation("insufficient_profile")
        try:
            jobs = await RecommendationRepository(self.db).match_jobs(
                profile, top_k=top_k, province=province
            )
        except Exception:
            logger.warning("recommendation lookup failed for chat_id=%s", chat_id, exc_info=True)
            return LeadJobRecommendation("unavailable")
        if not jobs:
            return LeadJobRecommendation("no_match")
        return LeadJobRecommendation("matched", tuple(jobs))

    async def find_active_jobs(self, query: str, *, top_k: int = 3):
        """Resolve an explicit role query against currently open jobs only."""
        from app.services.recommendation import RecommendationRepository

        return await RecommendationRepository(self.db).find_active_jobs(query, top_k=top_k)


__all__ = ["RetrievalRepository"]
