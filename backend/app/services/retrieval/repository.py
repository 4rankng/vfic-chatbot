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

import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)


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

    @staticmethod
    def _ann_enabled() -> bool:
        s = get_settings()
        return bool(s.rag_ann_enabled and s.embedding_dim == 3072)

    @staticmethod
    def _chunk_visibility(project_clause: str) -> str:
        """Shared WHERE predicate for chunk-scoping (vector + lexical paths).

        Extracted so both queries stay in sync when visibility rules change.
        """
        return (
            "d.status NOT IN ('ARCHIVED', 'FAILED') "
            "AND c.embedding IS NOT NULL "
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
            term
            for term in q.split()
            if len(term) >= 3 and term not in cls._LEXICAL_STOPWORDS
        ]
        seen: set[str] = set()
        return [term for term in terms if not (term in seen or seen.add(term))]

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
        """
        project_clause = ""
        params: dict[str, object] = {"emb": emb, "k": top_k, "filter": filter_json}
        if project_ids:
            project_clause = "AND d.project_id = ANY(CAST(:pids AS uuid[]))"
            params["pids"] = project_ids
        s = get_settings()
        if self._ann_enabled():
            vector_sql = (
                "WITH ann_candidates AS ("
                "  SELECT c.id "
                "  FROM knowledge_chunks c "
                "  JOIN knowledge_documents d ON d.id = c.document_id "
                "  WHERE " + self._chunk_visibility(project_clause) + " "
                "  ORDER BY c.embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072)) "
                "  LIMIT :candidate_k"
                ") "
                "SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                "FROM ann_candidates ac "
                "JOIN knowledge_chunks c ON c.id = ac.id "
                "WHERE 1 - (c.embedding <=> CAST(:emb AS vector)) >= :floor "
                "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                "LIMIT :k"
            )
            vector_params = {
                **params,
                "floor": self.SIMILARITY_FLOOR,
                "candidate_k": max(int(s.rag_ann_candidates), top_k),
            }
        else:
            vector_sql = (
                "SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                "FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON d.id = c.document_id "
                "WHERE " + self._chunk_visibility(project_clause) + " "
                "  AND 1 - (c.embedding <=> CAST(:emb AS vector)) >= :floor "
                "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                "LIMIT :k"
            )
            vector_params = {**params, "floor": self.SIMILARITY_FLOOR}
        vector_rows = (await self.db.execute(text(vector_sql), vector_params)).all()
        logger.debug(
            "match_documents vector branch: %d rows (floor=%.2f)",
            len(vector_rows), self.SIMILARITY_FLOOR,
        )
        terms = self._lexical_terms(query_text)
        if not terms:
            return vector_rows

        lexical_terms = terms[:8]
        term_predicates = [
            f"c.search_text ILIKE :term_like_{i}" for i, _term in enumerate(lexical_terms)
        ]
        lexical_prefilter = " OR ".join(term_predicates) or "false"
        lexical_params = {
            **params,
            "terms": lexical_terms,
            **{f"term_like_{i}": f"%{term}%" for i, term in enumerate(lexical_terms)},
        }
        lexical_rows = (
            await self.db.execute(
                text(
                    "WITH haystack AS ("
                    "  SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                    "         COALESCE(c.search_text, public.normalize_search_text("
                    "           COALESCE(c.content, '') || ' ' || COALESCE(c.source_quote, '') || ' ' || COALESCE(c.summary, '')"
                    "         )) AS searchable "
                    "  FROM knowledge_chunks c "
                    "  JOIN knowledge_documents d ON d.id = c.document_id "
                    "  WHERE " + self._chunk_visibility(project_clause) + " "
                    "    AND (c.search_text IS NULL OR " + lexical_prefilter + ") "
                    "), scored AS ("
                    "  SELECT id, content, source_quote, summary, metadata, "
                    "         (SELECT count(*) FROM unnest(CAST(:terms AS text[])) AS term(value) "
                    "          WHERE position(term.value IN searchable) > 0) AS lexical_hits "
                    "  FROM haystack"
                    ") "
                    "SELECT id, content, source_quote, summary, metadata, "
                    "  lexical_hits::double precision "
                    "  / GREATEST(CARDINALITY(CAST(:terms AS text[]))::double precision, 1.0) AS similarity "
                    "FROM scored "
                    "WHERE lexical_hits >= LEAST(2, CARDINALITY(CAST(:terms AS text[]))) "
                    "ORDER BY lexical_hits DESC "
                    "LIMIT :k"
                ),
                lexical_params,
            )
        ).all()

        # Lexical fills at most 2/3 of slots; vector always gets the remainder.
        lexical_cap = max(top_k * 2 // 3, 1)
        merged: list = []
        seen_ids: set[str] = set()
        lexical_count = 0
        for row in lexical_rows:
            rid = str(row.id)
            if rid not in seen_ids:
                seen_ids.add(rid)
                merged.append(row)
                lexical_count += 1
            if lexical_count >= lexical_cap:
                break
        for row in vector_rows:
            rid = str(row.id)
            if rid not in seen_ids:
                seen_ids.add(rid)
                merged.append(row)
            if len(merged) >= top_k:
                break
        logger.debug(
            "match_documents merged: %d rows (%d lexical, %d vector, top_k=%d)",
            len(merged), lexical_count, len(merged) - lexical_count, top_k,
        )
        return merged[:top_k]

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
                    "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                    "FROM knowledge_chunks c "
                    "JOIN knowledge_documents d ON d.id = c.document_id "
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
            len(rows), floor,
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


__all__ = ["RetrievalRepository"]
