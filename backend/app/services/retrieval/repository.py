"""Retrieval data-access for the agent layer.

Verbatim ports of the queries that ``app/graph/tools.py`` and
``app/graph/context.py`` previously ran inline, so the graph layer no longer owns
``text()`` SQL. Behaviour is unchanged: the tools now format the rows this repo
returns.

NO business logic, NO LLM/embedder calls — callers compute the embedding (a
graph-layer concern) and hand the repo a vector literal. Methods return SQLAlchemy
Row lists/scalars exactly as the inline ``db.execute(...).all()`` calls did.
"""
from __future__ import annotations

import json
import unicodedata
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RetrievalRepository:
    """Read-only retrieval queries backing the agent's tools + prompt assembly."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def match_memories(self, emb: str, top_k: int, filter_json: str) -> list:
        """Top-k memory rows for a chat (``match_memories`` SQL function)."""
        return (
            await self.db.execute(
                text(
                    "SELECT content, similarity FROM match_memories("
                    "CAST(:emb AS vector), :k, CAST(:filter AS jsonb))"
                ),
                {"emb": emb, "k": top_k, "filter": filter_json},
            )
        ).all()

    async def match_documents(
        self, emb: str, top_k: int, filter_json: str, *, project_ids: list[str] | None = None
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
        return (
            await self.db.execute(
                text(
                    "SELECT c.id, c.content, c.source_quote, c.summary, c.metadata, "
                    "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                    "FROM knowledge_chunks c "
                    "JOIN knowledge_documents d ON d.id = c.document_id "
                    "WHERE d.status NOT IN ('ARCHIVED', 'FAILED') "
                    "  AND c.embedding IS NOT NULL "
                    "  AND (CAST(:filter AS jsonb) = '{}'::jsonb OR c.metadata @> CAST(:filter AS jsonb)) "
                    f"  {project_clause} "  # noqa: S608 - clause is fixed above
                    "  AND ("
                    "    c.metadata #>> '{document_metadata,schema_version}' IS NULL "
                    "    OR ("
                    "      COALESCE(c.metadata #>> '{document_metadata,effective_from}', '0001-01-01')::date <= CURRENT_DATE "
                    "      AND (c.metadata #>> '{document_metadata,effective_to}' IS NULL "
                    "           OR (c.metadata #>> '{document_metadata,effective_to}')::date >= CURRENT_DATE)"
                    "    )"
                    "  ) "
                    "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                    "LIMIT :k"
                ),
                params,
            )
        ).all()

    @staticmethod
    def _normalize_text(value: str) -> str:
        no_marks = "".join(
            ch
            for ch in unicodedata.normalize("NFD", value.casefold())
            if unicodedata.category(ch) != "Mn"
        )
        no_marks = no_marks.replace("đ", "d")
        return " ".join(no_marks.split())

    @classmethod
    def _requested_bus_shifts(cls, question: str) -> list[str | None]:
        q = cls._normalize_text(question)
        wants_day = "ca ngay" in q
        wants_night = "ca dem" in q
        wants_admin = "hanh chinh" in q
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
        """name/slug/summary/index_card of active projects (master-index prompt block)."""
        return (
            await self.db.execute(
                text(
                    "SELECT name, slug, summary, index_card FROM projects WHERE is_active ORDER BY name"
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
                m.get("shift"),
                m.get("direction"),
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
            if len(route_keys) >= limit:
                break

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
                     AND br.route_variant = cr.route_variant
                     AND br.shift = cr.shift
                     AND br.direction = cr.direction
                     AND br.source_page = cr.source_page
                     AND COALESCE(br.mode, '') = cr.mode
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
