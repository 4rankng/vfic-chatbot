"""Bus-timetable retrieval: candidate routes via the SQL function, complete
route rows via the follow-up join.

The SQL function ranks one row per stop. For a stop-level query the agent
needs the complete route, so this repository identifies candidate route groups
through the function and then fetches all stops for those routes in stop_order.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.domain.text import normalize_vietnamese_text


class TimetableRepository:
    """Read-only bus-timetable queries backing the timetable tool."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _requested_bus_shifts(question: str) -> list[str | None]:
        # Strip punctuation so "ca ngày, ca đêm" → {"ca", "ngay", "ca", "dem"}
        q = normalize_vietnamese_text(question)
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
        # Filter out keys with NULL required fields (would fail JOIN on NULL = NULL).
        route_keys = [k for k in route_keys if k.get("company_name") and k.get("route_name")]
        if not route_keys:
            return fallback_rows

        complete_rows = (
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
                    JOIN projects p
                      ON p.id = br.project_id
                      AND (
                        (p.category_authority_started
                         AND br.source_category_revision_id IS NOT NULL)
                        OR
                        (NOT p.category_authority_started
                         AND br.source_category_revision_id IS NULL)
                      )
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
        selected: list = []
        selected_routes: set[tuple] = set()
        for row in complete_rows:
            mapping = row._mapping
            route_key = (
                mapping.get("company_name"),
                mapping.get("route_name"),
                mapping.get("route_variant"),
                mapping.get("shift"),
                mapping.get("direction"),
                mapping.get("source_page"),
                mapping.get("mode"),
            )
            if route_key not in selected_routes:
                if len(selected_routes) >= limit:
                    continue
                selected_routes.add(route_key)
            selected.append(row)
        return selected
