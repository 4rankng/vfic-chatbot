"""Phase 7 golden-gate tests for the bus-timetable Python port.

The PL/pgSQL ``rebuild_bus_timetable_from_documents()`` (alembic
0001_baseline.py:616-1079) was the authoritative spec; the pure-Python port
(``app.services.knowledge.bus_timetable``) must reproduce its output byte-for-byte.
These tests are the gate:

  T-0  ``normalize_search_text`` / ``normalize_bus_route_key`` (Python) == the SQL
       functions over a curated Vietnamese set — the đ/Đ fidelity proof (đ has no
       NFD decomposition but ``unaccent`` maps it to d).
  T-1  ``parse_bus_timetable(LGDisplay.txt)`` == the golden fixtures (pure Python).
  T-2  ``rebuild_bus_timetable(db)`` end-to-end (ingest -> parse -> persist) == golden.

The golden fixtures were captured from the verbatim SQL fn by
``scripts/capture_bus_timetable_golden.py``.
"""
from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest
from sqlalchemy import text

from app.graph.tools import search_bus_timetable
from app.services.knowledge.bus_timetable import (
    normalize_bus_route_key,
    normalize_search_text,
    parse_bus_timetable,
)
from app.services.knowledge.repository import rebuild_bus_timetable
from app.services.retrieval import RetrievalRepository

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_PATH = _REPO_ROOT / "kb" / "LGDisplay" / "LGDisplay.txt"
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bus_timetable"
_SOURCE_FILTER = "source_name = 'LGDisplay.txt' AND document_type = 'bus_schedule'"
_LEGACY_PROJECT_SLUG = "lg-display-bus-test"

# Curated Vietnamese probes (input -> expected normalize_search_text output),
# captured empirically from the SQL fn. Covers đ/Đ, every diacritic vowel, and the
# route-key alias inputs.
_NST_PROBES = [
    ("Hà Nội", "ha noi"),
    ("Đông Triều", "dong trieu"),
    ("Hưng Hà", "hung ha"),
    ("đ", "d"),
    ("Đ", "d"),
    ("Dương", "duong"),
    ("Chợ An Dương", "cho an duong"),
    ("KTX CĐ Bắc Bộ", "ktx cd bac bo"),
    ("TL Cầu Đầm", "tl cau dam"),
    ("Cầu Rào 1", "cau rao 1"),
]


def _load_fixture(name: str) -> list:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _route_dict(r) -> dict:
    return {
        "route_name": r.route_name, "route_no": r.route_no, "route_variant": r.route_variant,
        "route_group_key": r.route_group_key, "shift": r.shift, "direction": r.direction,
        "area": r.area, "mode": r.mode, "source_page": r.source_page, "notes": r.notes,
        "metadata": r.metadata,
    }


def _stop_dict(s) -> dict:
    return {
        "stop_order": s.stop_order, "stop_name": s.stop_name, "stop_aliases": list(s.stop_aliases),
        "scheduled_time": s.scheduled_time.isoformat() if isinstance(s.scheduled_time, time) else None,
        "raw_stop_text": s.raw_stop_text,
    }


def _service_day_dict(d) -> dict:
    return {
        "route_group_key": d.route_group_key, "route_group_name": d.route_group_name,
        "day_group": d.day_group, "day_label": d.day_label, "service_type": d.service_type,
        "availability_code": d.availability_code, "metadata": d.metadata,
    }


def _multiset(rows: list) -> list:
    return sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)


async def _cleanup_lgdisplay(db) -> None:
    """Remove every LGDisplay-test artifact so the rebuild test doesn't pollute the
    shared (persisted) test DB for later tests — bus_* / knowledge_sources /
    knowledge_documents are NOT in the transient-truncate fixture, and the rebuild
    upserts the canonical vfic project + 'LG Display' company, which would collide
    with test_jobs_dashboard._seed_company's company insert."""
    await db.execute(
        text(
            "DELETE FROM bus_stops WHERE route_id IN ("
            "  SELECT br.id FROM bus_routes br"
            "  JOIN knowledge_sources ks ON ks.id = br.knowledge_source_id"
            "  WHERE ks.source_name = 'LGDisplay.txt')"
        )
    )
    await db.execute(
        text(
            "DELETE FROM bus_routes br USING knowledge_sources ks "
            "WHERE ks.id = br.knowledge_source_id AND ks.source_name = 'LGDisplay.txt'"
        )
    )
    await db.execute(
        text(
            "DELETE FROM bus_route_service_days bsd USING knowledge_sources ks "
            "WHERE ks.id = bsd.knowledge_source_id AND ks.source_name = 'LGDisplay.txt'"
        )
    )
    await db.execute(text("DELETE FROM knowledge_sources WHERE source_name = 'LGDisplay.txt'"))
    await db.execute(text("DELETE FROM knowledge_documents WHERE file_name = 'LGDisplay.txt'"))
    await db.execute(text("DELETE FROM companies WHERE name = 'LG Display'"))
    await db.execute(text("DELETE FROM projects WHERE slug = :slug"), {"slug": _LEGACY_PROJECT_SLUG})
    await db.commit()


# --------------------------------------------------------------------------- T-0
@pytest.mark.asyncio
async def test_t0_normalize_matches_sql_functions(db_session) -> None:
    """Python normalizers == the SQL functions (đ/Đ fidelity proof)."""
    values_sql = ", ".join(f"(:p{i})" for i in range(len(_NST_PROBES)))
    params = {f"p{i}": src for i, (src, _) in enumerate(_NST_PROBES)}
    rows = (
        await db_session.execute(
            text(
                "SELECT s, normalize_search_text(s) AS ns, normalize_bus_route_key(s) AS nrk "
                f"FROM (VALUES {values_sql}) AS t(s)"
            ),
            params,
        )
    ).all()
    sql = {r.s: (r.ns, r.nrk) for r in rows}
    for src, want_nst in _NST_PROBES:
        assert normalize_search_text(src) == want_nst
        assert normalize_search_text(src) == sql[src][0], f"NST divergence on {src!r}"


def test_t0_route_key_alias_rewrites() -> None:
    assert normalize_bus_route_key("Cầu Rào 1") == "cau rao"
    assert normalize_bus_route_key("KTX CĐ Bắc Bộ") == "ktx cao dang bac bo"
    assert normalize_bus_route_key("TL Cầu Đầm") == "tien lang cau dam"
    assert normalize_bus_route_key("TL Hùng Thắng") == "tien lang hung thang"
    assert normalize_bus_route_key("") == ""
    assert normalize_bus_route_key(None) == ""


# --------------------------------------------------------------------------- T-1
def test_t1_parser_matches_golden() -> None:
    """Pure-Python parser output == golden fixtures (no DB)."""
    parsed = parse_bus_timetable(_SOURCE_PATH.read_text(encoding="utf-8"))
    py_routes = [_route_dict(r) for r in parsed.routes]
    py_stops = [_stop_dict(s) for r in parsed.routes for s in r.stops]
    py_sd = [_service_day_dict(d) for d in parsed.service_days]

    assert _multiset(py_routes) == _multiset(_load_fixture("golden_bus_routes.json"))
    assert _multiset(py_stops) == _multiset(_load_fixture("golden_bus_stops.json"))
    assert _multiset(py_sd) == _multiset(_load_fixture("golden_bus_route_service_days.json"))


# --------------------------------------------------------------------------- T-2
@pytest.mark.asyncio
async def test_t2_rebuild_matches_golden(db_session) -> None:
    """End-to-end: ingest a single whole-file doc -> rebuild -> bus tables == golden."""
    content = _SOURCE_PATH.read_text(encoding="utf-8")
    await _cleanup_lgdisplay(db_session)  # clean slate (idempotent)
    project_id = (
        await db_session.execute(
            text(
                "INSERT INTO projects(slug, name, is_active) "
                "VALUES (:slug, 'LG Display Bus Test', true) RETURNING id"
            ),
            {"slug": _LEGACY_PROJECT_SLUG},
        )
    ).scalar()
    doc_id = (
        await db_session.execute(
            text(
                "INSERT INTO knowledge_documents(file_name, source, status, raw_text, project_id) "
                "VALUES ('LGDisplay.txt', 'upload', 'PUBLISHED', :raw, :pid) RETURNING id"
            ),
            {"raw": content, "pid": project_id},
        )
    ).scalar()
    await db_session.execute(
        text("INSERT INTO knowledge_chunks(document_id, chunk_index, content) VALUES (:did, 0, :c)"),
        {"did": str(doc_id), "c": "LLM digest text without structured bus headings"},
    )
    await db_session.commit()

    routes_count, stops_count = await rebuild_bus_timetable(db_session)
    counts = _load_fixture("golden_counts.json")
    assert (routes_count, stops_count) == (counts["routes"], counts["stops"])

    routes = [
        dict(r)
        for r in (
            await db_session.execute(
                text(
                    "SELECT route_name, route_no, route_variant, route_group_key, shift, direction, "
                    "area, mode, source_page, notes, metadata::text AS metadata "
                    "FROM bus_routes br WHERE br.knowledge_source_id IN "
                    f"(SELECT id FROM knowledge_sources WHERE {_SOURCE_FILTER})"
                )
            )
        ).mappings().all()
    ]
    stops = [
        dict(r)
        for r in (
            await db_session.execute(
                text(
                    "SELECT bs.stop_order, bs.stop_name, bs.stop_aliases, "
                    "to_char(bs.scheduled_time, 'HH24:MI:SS') AS scheduled_time, bs.raw_stop_text "
                    "FROM bus_stops bs JOIN bus_routes br ON br.id = bs.route_id "
                    "WHERE br.knowledge_source_id IN "
                    f"(SELECT id FROM knowledge_sources WHERE {_SOURCE_FILTER})"
                )
            )
        ).mappings().all()
    ]
    service_days = [
        dict(r)
        for r in (
            await db_session.execute(
                text(
                    "SELECT route_group_key, route_group_name, day_group, day_label, service_type, "
                    "availability_code, metadata::text AS metadata FROM bus_route_service_days bsd "
                    "WHERE bsd.knowledge_source_id IN "
                    f"(SELECT id FROM knowledge_sources WHERE {_SOURCE_FILTER})"
                )
            )
        ).mappings().all()
    ]
    for rows in (routes, service_days):
        for r in rows:
            if isinstance(r.get("metadata"), str):
                r["metadata"] = json.loads(r["metadata"])

    try:
        assert _multiset(routes) == _multiset(_load_fixture("golden_bus_routes.json"))
        assert _multiset(stops) == _multiset(_load_fixture("golden_bus_stops.json"))
        assert _multiset(service_days) == _multiset(_load_fixture("golden_bus_route_service_days.json"))
    finally:
        await _cleanup_lgdisplay(db_session)  # teardown: don't pollute the shared test DB


@pytest.mark.asyncio
async def test_bus_search_completes_hao_quang_an_lao_day_and_night_routes(db_session) -> None:
    """A stop-level match must return complete route groups, not only the matched stop."""
    content = _SOURCE_PATH.read_text(encoding="utf-8")
    await _cleanup_lgdisplay(db_session)
    project_id = (
        await db_session.execute(
            text(
                "INSERT INTO projects(slug, name, is_active) "
                "VALUES (:slug, 'LG Display Bus Test', true) RETURNING id"
            ),
            {"slug": _LEGACY_PROJECT_SLUG},
        )
    ).scalar()
    doc_id = (
        await db_session.execute(
            text(
                "INSERT INTO knowledge_documents(file_name, source, status, raw_text, project_id) "
                "VALUES ('LGDisplay.txt', 'upload', 'PUBLISHED', :raw, :pid) RETURNING id"
            ),
            {"raw": content, "pid": project_id},
        )
    ).scalar()
    await db_session.execute(
        text("INSERT INTO knowledge_chunks(document_id, chunk_index, content) VALUES (:did, 0, :c)"),
        {"did": str(doc_id), "c": "LLM digest text without structured bus headings"},
    )
    await db_session.commit()

    try:
        await rebuild_bus_timetable(db_session)
        rows = await RetrievalRepository(db_session).search_bus_timetable(
            company="LG Display",
            question="mấy giờ đón ở Cty TNHH Hào Quang ca ngày, ca đêm, tuyến An Lão",
            limit=50,
        )
        stop_pairs = {
            (r.route_name, r.shift, r.stop_name, r.scheduled_time)
            for r in rows
            if r.route_name == "An Lão"
        }
        for expected in {
            ("An Lão", "day", "Cty TNHH Hào Quang", "06:35"),
            ("An Lão", "day", "BV An Lão 2", "06:50"),
            ("An Lão", "day", "Trung tâm giống cây trồng", "06:55"),
            ("An Lão", "day", "Ngã 5 Kiến An", "07:00"),
            ("An Lão", "day", "Cống Đôi Kiến An", "07:05"),
            ("An Lão", "day", "Quân đoàn 679", "07:10"),
            ("An Lão", "day", "LGD", None),
            ("An Lão", "night", "Cty TNHH Hào Quang", "18:35"),
            ("An Lão", "night", "BV An Lão 2", "18:50"),
            ("An Lão", "night", "Trung tâm giống cây trồng", "18:55"),
            ("An Lão", "night", "Ngã 5 Kiến An", "19:00"),
            ("An Lão", "night", "Cống Đôi Kiến An", "19:05"),
            ("An Lão", "night", "Quân đoàn 679", "19:10"),
            ("An Lão", "night", "LGD", None),
        }:
            assert expected in stop_pairs

        formatted = await search_bus_timetable(
            db_session,
            "Cty TNHH Hào Quang",
            "mấy giờ đón ở Cty TNHH Hào Quang ca ngày, ca đêm, tuyến An Lão",
        )
        assert "Cty TNHH Hào Quang: 06:35" in formatted
        assert "BV An Lão 2: 06:50" in formatted
        assert "Cống Đôi Kiến An: 19:05" in formatted
        assert "LGD: chưa có giờ trong nguồn" in formatted
    finally:
        await _cleanup_lgdisplay(db_session)


# ---------------------------------------------------------------------------
# F6: Bus shift detection recognises "ca sáng" / "buổi sáng"
def test_requested_bus_shifts_ca_sang():
    shifts = RetrievalRepository._requested_bus_shifts("xe ca sáng đi Hào Quang")
    assert shifts == ["day"]


def test_requested_bus_shifts_buoi_sang():
    shifts = RetrievalRepository._requested_bus_shifts("buổi sáng làm gì")
    assert shifts == ["day"]


def test_requested_bus_shifts_ca_ngay_still_works():
    shifts = RetrievalRepository._requested_bus_shifts("ca ngày xe nào")
    assert shifts == ["day"]


def test_requested_bus_shifts_ca_dem():
    shifts = RetrievalRepository._requested_bus_shifts("ca đêm về")
    assert shifts == ["night"]
