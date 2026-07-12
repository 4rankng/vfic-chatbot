"""Raw-SQL persistence for the parsed bus timetable (the data-access layer).

``BusTimetableRepo.upsert`` mirrors the write side of
``rebuild_bus_timetable_from_documents()`` (alembic 0001_baseline.py:658-1063):
idempotent project/company/source upsert, three scoped DELETEs, then route /
stop / service-day UPSERTs with the exact ``ON CONFLICT`` clauses. The parser
produces the rows; this repo owns the SQL. No business logic.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.bus_timetable.models import ParsedBusTimetable

# Default source identity — matches rebuild_bus_timetable_from_documents() defaults;
# the wrapper always calls with these (the SQL fn is invoked with no args).
_DEFAULT_PROJECT_SLUG = "vfic"
_DEFAULT_COMPANY_NAME = "LG Display"
_DEFAULT_SOURCE_NAME = "LGDisplay.txt"
_LG_DISPLAY_ALIASES = ("LGD", "LG Display Việt Nam", "LG Display Vietnam")


class BusTimetableRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(
        self,
        parsed: ParsedBusTimetable,
        *,
        project_slug: str = _DEFAULT_PROJECT_SLUG,
        company_name: str = _DEFAULT_COMPANY_NAME,
        source_name: str = _DEFAULT_SOURCE_NAME,
        source_ref: str | None = None,
        version: str = "",
        source_type: str = "text",
    ) -> tuple[int, int]:
        """Persist a parsed timetable: clean slate for the source, then upsert all rows.

        Returns ``(routes_rebuilt, stops_rebuilt)`` like the SQL function.
        """
        db = self.db
        company_aliases = (
            list(_LG_DISPLAY_ALIASES)
            if company_name.casefold() == "LG Display".casefold()
            else [company_name]
        )

        # --- project / company / knowledge_source (idempotent upserts) ---
        project_id = (
            await db.execute(
                text(
                    "INSERT INTO projects (slug, name) VALUES (:slug, upper(:slug)) "
                    "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                ),
                {"slug": project_slug},
            )
        ).scalar()
        company_id = (
            await db.execute(
                text(
                    "INSERT INTO companies (project_id, name, aliases) "
                    "VALUES (CAST(:pid AS uuid), :cname, CAST(:aliases AS text[])) "
                    "ON CONFLICT (project_id, name) DO UPDATE SET aliases = EXCLUDED.aliases "
                    "RETURNING id"
                ),
                {"pid": str(project_id), "cname": company_name, "aliases": company_aliases},
            )
        ).scalar()
        source_id = (
            await db.execute(
                text(
                    "INSERT INTO knowledge_sources "
                    "(project_id, company_id, source_name, source_type, document_type, "
                    " source_ref, version, status, metadata) "
                    "VALUES (CAST(:pid AS uuid), CAST(:cid AS uuid), :sname, :stype, 'bus_schedule', "
                    "        :sref, coalesce(:ver, ''), 'published', "
                    "        CAST(:meta AS jsonb) || jsonb_build_object('rebuilt_at', now())) "
                    "ON CONFLICT (project_id, company_id, source_name, document_type, version) DO UPDATE "
                    "SET source_ref = EXCLUDED.source_ref, source_type = EXCLUDED.source_type, "
                    "    status = EXCLUDED.status, metadata = EXCLUDED.metadata, updated_at = now() "
                    "RETURNING id"
                ),
                {
                    "pid": str(project_id),
                    "cid": str(company_id),
                    "sname": source_name,
                    "stype": source_type,
                    "sref": source_ref,
                    "ver": version,
                    "meta": json.dumps({"file_name": source_name}, ensure_ascii=False),
                },
            )
        ).scalar()

        # --- clean slate for this source's bus rows (scoped DELETEs) ---
        await db.execute(
            text(
                "DELETE FROM bus_stops WHERE route_id IN ("
                "  SELECT br.id FROM bus_routes br"
                "  JOIN knowledge_sources ks ON ks.id = br.knowledge_source_id"
                "  WHERE ks.id = CAST(:sid AS uuid))"
            ),
            {"sid": str(source_id)},
        )
        await db.execute(
            text(
                "DELETE FROM bus_routes br USING knowledge_sources ks "
                "WHERE ks.id = br.knowledge_source_id AND ks.id = CAST(:sid AS uuid)"
            ),
            {"sid": str(source_id)},
        )
        await db.execute(
            text(
                "DELETE FROM bus_route_service_days bsd USING knowledge_sources ks "
                "WHERE ks.id = bsd.knowledge_source_id AND ks.id = CAST(:sid AS uuid)"
            ),
            {"sid": str(source_id)},
        )

        # --- routes + their stops ---
        pid, cid, sid = str(project_id), str(company_id), str(source_id)
        stops_rebuilt = 0
        for route in parsed.routes:
            route_id = (
                await db.execute(
                    text(
                        "INSERT INTO bus_routes "
                        "(project_id, company_id, knowledge_source_id, route_name, route_no, "
                        " route_variant, route_group_key, shift, direction, area, mode, "
                        " source_page, notes, metadata) "
                        "VALUES (CAST(:pid AS uuid), CAST(:cid AS uuid), CAST(:sid AS uuid), :rname, :rno, "
                        "        :rvar, :rgkey, :shift, :dir, :area, :mode, :page, :notes, CAST(:meta AS jsonb)) "
                        "ON CONFLICT (company_id, route_name, route_variant, shift, direction, source_page, mode) "
                        "DO UPDATE SET route_no = EXCLUDED.route_no, route_group_key = EXCLUDED.route_group_key, "
                        "  area = EXCLUDED.area, notes = EXCLUDED.notes, metadata = EXCLUDED.metadata, "
                        "  knowledge_source_id = EXCLUDED.knowledge_source_id "
                        "RETURNING id"
                    ),
                    {
                        "pid": pid,
                        "cid": cid,
                        "sid": sid,
                        "rname": route.route_name,
                        "rno": route.route_no,
                        "rvar": route.route_variant,
                        "rgkey": route.route_group_key,
                        "shift": route.shift,
                        "dir": route.direction,
                        "area": route.area,
                        "mode": route.mode,
                        "page": route.source_page,
                        "notes": route.notes,
                        "meta": json.dumps(route.metadata, ensure_ascii=False),
                    },
                )
            ).scalar()
            # Bulk-insert stops for this route (1 round-trip instead of N).
            if route.stops:
                await db.execute(
                    text(
                        "INSERT INTO bus_stops "
                        "(route_id, stop_order, stop_name, stop_aliases, scheduled_time, raw_stop_text) "
                        "VALUES (CAST(:rid AS uuid), :order, :sname, CAST(:aliases AS text[]), :stime, :raw) "
                        "ON CONFLICT (route_id, stop_order) DO UPDATE "
                        "SET stop_name = EXCLUDED.stop_name, stop_aliases = EXCLUDED.stop_aliases, "
                        "    scheduled_time = EXCLUDED.scheduled_time, raw_stop_text = EXCLUDED.raw_stop_text"
                    ),
                    [
                        {
                            "rid": str(route_id),
                            "order": stop.stop_order,
                            "sname": stop.stop_name,
                            "aliases": list(stop.stop_aliases),
                            "stime": stop.scheduled_time,
                            "raw": stop.raw_stop_text,
                        }
                        for stop in route.stops
                    ],
                )
            stops_rebuilt += len(route.stops)

        # --- weekly service-day matrix (bulk: 1 round-trip instead of N) ---
        if parsed.service_days:
            await db.execute(
                text(
                    "INSERT INTO bus_route_service_days "
                    "(project_id, company_id, knowledge_source_id, route_group_key, route_group_name, "
                    " day_group, day_label, service_type, availability_code, metadata) "
                    "VALUES (CAST(:pid AS uuid), CAST(:cid AS uuid), CAST(:sid AS uuid), :rgkey, :rgname, "
                    "        :dgroup, :dlabel, :stype, :acode, CAST(:meta AS jsonb)) "
                    "ON CONFLICT (company_id, route_group_key, day_group, service_type) DO UPDATE "
                    "SET project_id = EXCLUDED.project_id, knowledge_source_id = EXCLUDED.knowledge_source_id, "
                    "    route_group_name = EXCLUDED.route_group_name, day_label = EXCLUDED.day_label, "
                    "    availability_code = EXCLUDED.availability_code, metadata = EXCLUDED.metadata"
                ),
                [
                    {
                        "pid": pid,
                        "cid": cid,
                        "sid": sid,
                        "rgkey": day.route_group_key,
                        "rgname": day.route_group_name,
                        "dgroup": day.day_group,
                        "dlabel": day.day_label,
                        "stype": day.service_type,
                        "acode": day.availability_code,
                        "meta": json.dumps(day.metadata, ensure_ascii=False),
                    }
                    for day in parsed.service_days
                ],
            )

        # route_group_key is already set per-route by the parser (Python
        # normalize_bus_route_key), so the SQL fn's null/empty post-fix
        # (alembic 0001_baseline.py:1060-1063) is a no-op here — nothing to fix up.

        await db.commit()
        routes_rebuilt = (
            await db.execute(
                text(
                    "SELECT count(*)::int FROM bus_routes WHERE knowledge_source_id = CAST(:sid AS uuid)"
                ),
                {"sid": sid},
            )
        ).scalar()
        return int(routes_rebuilt), int(stops_rebuilt)
