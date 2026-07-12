"""Capture the golden bus-timetable dataset from the CURRENT PL/pgSQL function.

One-shot characterization harness for the rebuild_bus_timetable_from_documents()
port (Phase 7). The PL/pgSQL function is the authoritative spec; this script
materialises its output on the canonical input (kb/LGDisplay/LGDisplay.txt) into
committed JSON fixtures so the Python port can prove byte-identical behaviour.

Deterministic by construction: no LLM, no embedder, no Drive — one document, one
chunk (whole-file content), then SELECT the verbatim SQL fn and dump the three
result relations with volatile columns dropped and a stable sort order.

Run:  cd backend && APP_ENV=development .venv/bin/python scripts/capture_bus_timetable_golden.py
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

# The canonical bus-timetable source (repo root /kb/LGDisplay/LGDisplay.txt).
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = REPO_ROOT / "kb" / "LGDisplay" / "LGDisplay.txt"
SOURCE_NAME = "LGDisplay.txt"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "bus_timetable"

# knowledge_sources row the function upserts (defaults: company 'LG Display',
# source_name 'LGDisplay.txt', document_type 'bus_schedule').
SOURCE_FILTER_SQL = "source_name = 'LGDisplay.txt' AND document_type = 'bus_schedule'"


def _row_to_plain(value: object) -> object:
    """Normalise asyncpg/PG returns into JSON-stable scalars."""
    import datetime  # noqa: PLC0415

    if isinstance(value, datetime.time):
        return value.isoformat()  # time(6,40) -> "06:40:00"
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _dump(rows: list, path: Path) -> None:
    payload = [{k: _row_to_plain(v) for k, v in row.items()} for row in rows]
    text_out = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    path.write_text(text_out + "\n", encoding="utf-8")


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    content = SOURCE_PATH.read_text(encoding="utf-8")
    print(f"loaded {SOURCE_PATH}: {len(content)} chars")

    async with Session() as db:
        # 1. Clean slate: bus rows + any prior LGDisplay doc (idempotent re-runs).
        await db.execute(
            text(
                "DELETE FROM bus_stops WHERE route_id IN ("
                "  SELECT br.id FROM bus_routes br"
                "  JOIN knowledge_sources ks ON ks.id = br.knowledge_source_id"
                f"  WHERE {SOURCE_FILTER_SQL})"
            )
        )
        await db.execute(
            text(
                "DELETE FROM bus_routes br USING knowledge_sources ks "
                "WHERE ks.id = br.knowledge_source_id AND " + SOURCE_FILTER_SQL
            )
        )
        await db.execute(
            text(
                "DELETE FROM bus_route_service_days bsd USING knowledge_sources ks "
                "WHERE ks.id = bsd.knowledge_source_id AND " + SOURCE_FILTER_SQL
            )
        )
        await db.execute(
            text(
                "DELETE FROM knowledge_chunks WHERE document_id IN ("
                "  SELECT id FROM knowledge_documents WHERE file_name = :fn)"
            ),
            {"fn": SOURCE_NAME},
        )
        await db.execute(
            text("DELETE FROM knowledge_documents WHERE file_name = :fn"), {"fn": SOURCE_NAME}
        )

        # 2. Deterministic ingest: one PUBLISHED doc + one whole-file chunk.
        doc_id = (
            await db.execute(
                text(
                    "INSERT INTO knowledge_documents(file_name, source, status, raw_text, metadata) "
                    "VALUES (:fn, 'upload', 'PUBLISHED', :raw, CAST(:meta AS jsonb)) RETURNING id"
                ),
                {"fn": SOURCE_NAME, "raw": content, "meta": json.dumps({"file_name": SOURCE_NAME})},
            )
        ).scalar()
        await db.execute(
            text(
                "INSERT INTO knowledge_chunks(document_id, chunk_index, content) VALUES (:did, 0, :content)"
            ),
            {"did": doc_id, "content": content},
        )
        await db.commit()

        # 3. Run the CURRENT verbatim SQL function.
        result = (await db.execute(text("SELECT rebuild_bus_timetable_from_documents()"))).scalar()
        routes_count, stops_count = result
        await db.commit()
        print(f"SQL fn returned: routes_rebuilt={routes_count}, stops_rebuilt={stops_count}")

        # 4. Dump the three relations (volatile cols dropped; stable sort).
        routes = (
            (
                await db.execute(
                    text(
                        "SELECT route_name, route_no, route_variant, route_group_key, shift, direction, "
                        "area, mode, source_page, notes, metadata::text AS metadata "
                        "FROM bus_routes br WHERE br.knowledge_source_id IN "
                        "(SELECT id FROM knowledge_sources WHERE " + SOURCE_FILTER_SQL + ") "
                        "ORDER BY route_name, route_variant, shift, direction, source_page, mode"
                    )
                )
            )
            .mappings()
            .all()
        )

        stops = (
            (
                await db.execute(
                    text(
                        "SELECT bs.stop_order, bs.stop_name, bs.stop_aliases, bs.scheduled_time, bs.raw_stop_text "
                        "FROM bus_stops bs JOIN bus_routes br ON br.id = bs.route_id "
                        "WHERE br.knowledge_source_id IN "
                        "(SELECT id FROM knowledge_sources WHERE " + SOURCE_FILTER_SQL + ") "
                        "ORDER BY br.route_name, br.route_variant, br.shift, br.direction, br.source_page, bs.stop_order"
                    )
                )
            )
            .mappings()
            .all()
        )

        service_days = (
            (
                await db.execute(
                    text(
                        "SELECT route_group_key, route_group_name, day_group, day_label, service_type, "
                        "availability_code, metadata::text AS metadata FROM bus_route_service_days bsd "
                        "WHERE bsd.knowledge_source_id IN "
                        "(SELECT id FROM knowledge_sources WHERE " + SOURCE_FILTER_SQL + ") "
                        "ORDER BY route_group_key, day_group, service_type"
                    )
                )
            )
            .mappings()
            .all()
        )

    await engine.dispose()

    routes = [dict(r) for r in routes]
    stops = [dict(r) for r in stops]
    service_days = [dict(r) for r in service_days]

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    # Normalise metadata text -> dict so the fixture is structured JSON (and sort_keys stabilises it).
    for rows in (routes, service_days):
        for r in rows:
            if "metadata" in r and isinstance(r["metadata"], str):
                r["metadata"] = json.loads(r["metadata"])
    # stop_aliases arrives as a list already; keep as-is.

    _dump(list(routes), FIXTURE_DIR / "golden_bus_routes.json")
    _dump(list(stops), FIXTURE_DIR / "golden_bus_stops.json")
    _dump(list(service_days), FIXTURE_DIR / "golden_bus_route_service_days.json")
    (FIXTURE_DIR / "golden_counts.json").write_text(
        json.dumps(
            {
                "routes": int(routes_count),
                "stops": int(stops_count),
                "service_days": len(service_days),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"wrote {len(routes)} routes, {len(stops)} stops, {len(service_days)} service_days "
        f"-> {FIXTURE_DIR}"
    )


if __name__ == "__main__":
    import asyncio  # noqa: PLC0415

    asyncio.run(main())
