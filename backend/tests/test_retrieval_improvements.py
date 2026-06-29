"""Regression tests for retrieval improvements (Agent X evidence-density parity).

Guards the 2026-06-29 retrieval fix:
1. search_knowledge returns full content — no silent [:300] truncation.
2. Stop-level bus query returns the COMPLETE route (two-phase completion).
3. "ca ngày và ca đêm" dispatches BOTH shifts.
4. _normalize_text / _requested_bus_shifts unit correctness.
"""
from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import text

from app.graph.tools import search_bus_timetable, search_knowledge
from app.services.knowledge.canonical import load_template
from app.services.knowledge.pipeline import KnowledgePipeline
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval import RetrievalRepository

VEC = [0.01] * 3072


class _FakeEmbedder:
    async def embed(self, _t):
        return list(VEC)

    async def batch(self, texts):
        return [list(VEC) for _ in texts]

    __call__ = embed


async def _guard_llm(_system: str, _user: str) -> str:
    raise AssertionError("canonical ingest must not call the LLM")


async def emb(_text: str):
    return list(VEC)


# ---------------------------------------------------------------------------
# Unit tests: no DB needed (sync)
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_strips_diacritics(self):
        assert RetrievalRepository._normalize_text("Hào Quang") == "hao quang"

    def test_normalizes_whitespace(self):
        assert RetrievalRepository._normalize_text("  ca  ngày  ") == "ca ngay"

    def test_lowercases(self):
        assert RetrievalRepository._normalize_text("CA ĐÊM") == "ca dem"

    def test_combined(self):
        assert (
            RetrievalRepository._normalize_text("Tuyến An Lão CA NGÀY")
            == "tuyen an lao ca ngay"
        )


class TestRequestedBusShifts:
    def test_day_only(self):
        assert RetrievalRepository._requested_bus_shifts("xe ca ngày") == ["day"]

    def test_night_only(self):
        assert RetrievalRepository._requested_bus_shifts("xe ca đêm") == ["night"]

    def test_both_day_and_night(self):
        result = RetrievalRepository._requested_bus_shifts("ca ngày và ca đêm")
        assert result == ["day", "night"]

    def test_no_shift_returns_none(self):
        assert RetrievalRepository._requested_bus_shifts("tuyến An Lão") == [None]

    def test_admin_shift(self):
        assert (
            RetrievalRepository._requested_bus_shifts("xe hành chính") == ["admin"]
        )

    def test_all_three(self):
        result = RetrievalRepository._requested_bus_shifts(
            "ca ngày ca đêm hành chính"
        )
        assert result == ["day", "night", "admin"]


# ---------------------------------------------------------------------------
# Integration tests: need DB (async)
# ---------------------------------------------------------------------------

# Fixed 3072-dim vector literal for seeding knowledge chunks.
VEC_LIT = "[" + ",".join(["0.01000000"] * 3072) + "]"

# IDs for directly-inserted bus fixtures (deterministic, no FK conflicts).
_PID = "11111111-aaaa-bbbb-cccc-dddddddddddd"
_CID = "22222222-aaaa-bbbb-cccc-dddddddddddd"
_SID = "33333333-aaaa-bbbb-cccc-dddddddddddd"
_DAY_ROUTE = "44444444-0001-0001-0001-000000000001"
_NIGHT_ROUTE = "44444444-0002-0002-0002-000000000002"

# 8 stops on the An Lão route (day = 06:xx, night = 18:xx).
_STOPS_DAY = [
    ("Cty TNHH Hào Quang", datetime.time(6, 35)),
    ("Bến xe Niệm Nghĩa", datetime.time(6, 45)),
    ("Ngã 3 An Hưng", datetime.time(6, 55)),
    ("Ngã 4 An Đồng", datetime.time(7, 5)),
    ("KCN Lê Chân", datetime.time(7, 15)),
    ("Ngã 3 Đồng Hòa", datetime.time(7, 25)),
    ("TD Plaza", datetime.time(7, 35)),
    ("LGD", datetime.time(7, 45)),
]

_STOPS_NIGHT = [
    ("Cty TNHH Hào Quang", datetime.time(18, 35)),
    ("Bến xe Niệm Nghĩa", datetime.time(18, 45)),
    ("Ngã 3 An Hưng", datetime.time(18, 55)),
    ("Ngã 4 An Đồng", datetime.time(19, 5)),
    ("KCN Lê Chân", datetime.time(19, 15)),
    ("Ngã 3 Đồng Hòa", datetime.time(19, 25)),
    ("TD Plaza", datetime.time(19, 35)),
    ("LGD", datetime.time(19, 45)),
]


async def _seed_bus_data_directly(db_session, clean_kb):
    """Insert project + company + knowledge_source + routes + stops directly.

    The two-phase completion query in ``search_bus_timetable`` joins
    ``companies/bus_routes/bus_stops`` — it does NOT go through the SQL
    function for phase 2, so direct inserts are sufficient to exercise the
    completion logic.  Phase 1 still uses the SQL function, but we test the
    formatting and completion separately.
    """
    # Ensure project exists (seeded by conftest or create one).
    await db_session.execute(
        text(
            "INSERT INTO projects(id, name, slug, is_active) "
            "VALUES (CAST(:id AS uuid), :name, :slug, true) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": _PID, "name": "LG Display Test", "slug": "lg-display-test"},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge_sources(id, project_id, source_name, source_type, "
            "document_type, version, status) "
            "VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name, 'text', 'bus_timetable', '1', 'published') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": _SID, "pid": _PID, "name": "Multi-Stop Test"},
    )
    await db_session.execute(
        text(
            "INSERT INTO companies(id, project_id, name) "
            "VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": _CID, "pid": _PID, "name": "LG Display"},
    )
    for route_id, shift, stops in [
        (_DAY_ROUTE, "day", _STOPS_DAY),
        (_NIGHT_ROUTE, "night", _STOPS_NIGHT),
    ]:
        await db_session.execute(
            text(
                "INSERT INTO bus_routes(id, project_id, company_id, knowledge_source_id, "
                "route_name, route_variant, shift, direction, area, mode, source_page, "
                "route_group_key) "
                "VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:cid AS uuid), "
                "CAST(:sid AS uuid), :name, :variant, :shift, 'outbound', :area, :mode, '', "
                ":group_key) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "id": route_id,
                "pid": _PID,
                "cid": _CID,
                "sid": _SID,
                "name": "An Lão",
                "variant": "1",
                "shift": shift,
                "area": "Hải Phòng",
                "mode": "standard",
                "group_key": "an_lao",
            },
        )
        for idx, (stop_name, stop_time) in enumerate(stops, start=1):
            await db_session.execute(
                text(
                    "INSERT INTO bus_stops(id, route_id, stop_order, stop_name, scheduled_time) "
                    "VALUES (CAST(:id AS uuid), CAST(:rid AS uuid), :order, :name, :time) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": route_id,
                    "order": idx,
                    "name": stop_name,
                    "time": stop_time,
                },
            )
    await db_session.commit()


@pytest.mark.asyncio
async def test_search_knowledge_no_truncation(db_session, clean_kb):
    """Content longer than 300 chars must NOT be silently clipped."""
    long_content = "X" * 500
    await db_session.execute(
        text(
            "INSERT INTO knowledge_documents(id, drive_file_id, file_name, source, status, raw_text, metadata) "
            "VALUES (CAST(:id AS uuid), :df, :fn, :src, :status, :raw, CAST('{}' AS jsonb)) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": "aaaaaaaa-bbbb-cccc-dddd-000000000099",
            "df": "f1",
            "fn": "long.pdf",
            "src": "google_drive",
            "status": "PUBLISHED",
            "raw": "x",
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata) "
            "VALUES (CAST(:did AS uuid), 0, :content, CAST(:e AS vector), CAST('{}' AS jsonb)) "
            "ON CONFLICT (document_id, chunk_index) DO NOTHING"
        ),
        {
            "did": "aaaaaaaa-bbbb-cccc-dddd-000000000099",
            "content": long_content,
            "e": VEC_LIT,
        },
    )
    await db_session.commit()

    result = await search_knowledge(db_session, emb, "test query")
    assert long_content in result, "search_knowledge must return full content without truncation"


@pytest.mark.asyncio
async def test_stop_level_query_returns_complete_route(db_session, clean_kb):
    """Asking about 'Hào Quang' must return ALL 8 stops of the An Lão route,
    not just the single matching stop — the two-phase completion guarantees this."""
    await _seed_bus_data_directly(db_session, clean_kb)

    # Phase 1: SQL function finds candidate route keys via trigram match.
    # Phase 2: direct JOIN fetches ALL stops for those routes.
    rows = await RetrievalRepository(db_session).search_bus_timetable(
        company="LG Display", question="Hào Quang", limit=50
    )
    assert rows, "Hào Quang query should find the An Lão route"

    stops = {getattr(r, "stop_name", "") for r in rows}
    for expected in [
        "Cty TNHH Hào Quang",
        "Bến xe Niệm Nghĩa",
        "Ngã 3 An Hưng",
        "Ngã 4 An Đồng",
        "KCN Lê Chân",
        "Ngã 3 Đồng Hòa",
        "TD Plaza",
        "LGD",
    ]:
        assert expected in stops, f"Expected stop '{expected}' in complete route, got {stops}"


@pytest.mark.asyncio
async def test_both_shifts_returned_for_ca_ngay_va_ca_dem(db_session, clean_kb):
    """Asking about 'ca ngày và ca đêm' must return both the 06:35 day route
    and the 18:35 night route for the same An Lão line."""
    await _seed_bus_data_directly(db_session, clean_kb)

    rows = await RetrievalRepository(db_session).search_bus_timetable(
        company="LG Display", question="Hào Quang ca ngày và ca đêm", limit=50
    )
    assert rows, "query should find the An Lão route for both shifts"

    pairs = {
        (getattr(r, "stop_name", ""), getattr(r, "scheduled_time", ""))
        for r in rows
    }
    assert ("Cty TNHH Hào Quang", "06:35") in pairs, (
        "Day shift Hào Quang 06:35 must be present"
    )
    assert ("Cty TNHH Hào Quang", "18:35") in pairs, (
        "Night shift Hào Quang 18:35 must be present"
    )


@pytest.mark.asyncio
async def test_bus_timetable_tool_formats_all_stops(db_session, clean_kb):
    """The formatted tool output must include every stop with its time."""
    await _seed_bus_data_directly(db_session, clean_kb)

    result = await search_bus_timetable(db_session, "LG Display", "Hào Quang")
    assert "Cty TNHH Hào Quang" in result
    assert "LGD" in result, "last stop (destination) must appear in formatted output"
    assert "06:35" in result, "scheduled time must appear in formatted output"


@pytest.mark.asyncio
async def test_canonical_template_still_reachable(db_session, clean_kb):
    """Regression guard: the original canonical template TD Plaza route is still
    reachable after the two-phase refactoring (mirrors test_canonical_bus_retrieval)."""
    doc = await KnowledgeService(db_session).upload_bytes(
        "canonical-bus.md",
        "text/markdown",
        load_template().encode("utf-8"),
        require_canonical=True,
    )
    await KnowledgePipeline(db_session, _FakeEmbedder(), _guard_llm).run(doc)
    await db_session.refresh(doc)

    rows = await RetrievalRepository(db_session).search_bus_timetable(
        company="LG Display", question="td plaza", limit=20
    )
    assert rows, "TD Plaza route must be reachable"
    assert any(
        "TD Plaza" == (getattr(r, "route_name", "") or "") for r in rows
    )
