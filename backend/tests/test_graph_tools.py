"""Characterization tests for graph/tools.py — the agent's retrieval tool layer.

These pin two things that every graph-layer refactor must preserve:

* the ``TOOLS_REGISTRY`` contract (a tool cannot silently disappear or rename),
* the Vietnamese formatting + empty / not-found branch behavior of each tool.

No DB, embeddings, Redis, or LLM: a fake embedder + a fake ``RetrievalRepository``
stand in for the outside world. These are characterization tests — they pin
*current* behavior so refactors stay behavior-preserving.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.graph import tools
from app.graph.tools import (
    TOOLS_REGISTRY,
    _format_knowledge_row,
    get_product_features,
    list_active_projects,
    search_bus_timetable,
    search_knowledge,
    search_user_memory,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    """A callable async embedder returning a fixed vector and recording calls."""

    def __init__(self, vec: list[float] | None = None) -> None:
        self._vec = vec or [0.1] * 8
        self.calls: list[str] = []

    async def __call__(self, query: str) -> list[float]:
        self.calls.append(query)
        return self._vec


def _install_repo(monkeypatch, **methods):
    """Replace ``RetrievalRepository`` inside the tools module with a fake.

    Each kwarg is ``name -> async callable(self, ...)`` installed as a method.
    Unconfigured methods default to returning an empty list / None.
    """

    class _Repo:
        def __init__(self, db) -> None:
            self.db = db

    for name, fn in methods.items():
        setattr(_Repo, name, fn)

    monkeypatch.setattr(tools, "RetrievalRepository", _Repo)
    return _Repo


@pytest.fixture
def no_cache_io(monkeypatch):
    """Disable RAG caching AND neutralize the cache helpers so no Redis is hit.

    ``search_user_memory``'s empty-results branch calls ``cache_set_json``
    unconditionally; without neutralizing it the test would touch a live Redis.
    """

    class _S:
        rag_cache_enabled = False
        embedding_provider = "openrouter"
        openrouter_embedding_model = "openai/text-embedding-3-large"
        gemini_embedding_model = "gemini-embedding-2"
        embedding_dim = 8
        embedding_cache_ttl_seconds = 60
        rag_result_cache_ttl_seconds = 60

    monkeypatch.setattr(tools, "get_settings", lambda: _S())

    async def _noop_get(*a, **k):
        return None

    async def _noop_set(*a, **k):
        return None

    async def _noop_version(*a, **k):
        return "0"

    monkeypatch.setattr(tools, "cache_get_json", _noop_get)
    monkeypatch.setattr(tools, "cache_set_json", _noop_set)
    monkeypatch.setattr(tools, "cache_version", _noop_version)
    return _S()


# ---------------------------------------------------------------------------
# Registry contract
# ---------------------------------------------------------------------------


def test_tools_registry_exposes_expected_tools():
    """No tool silently disappears/renames during a refactor (F-CRIT-2 guard)."""
    assert set(TOOLS_REGISTRY) == {
        "search_user_memory",
        "search_knowledge",
        "list_active_projects",
        "search_bus_timetable",
        "get_product_features",
    }
    assert all(callable(fn) for fn in TOOLS_REGISTRY.values())


# ---------------------------------------------------------------------------
# _format_knowledge_row — the citation formatter (pure)
# ---------------------------------------------------------------------------


def test_format_row_prefers_source_quote_then_summary():
    row = SimpleNamespace(
        content="ignored-when-quote-present",
        source_quote="Lương 15 triệu",
        summary="Mô tả ngắn",
        metadata={"citation": {"label": "JD"},
                  "document_metadata": {"title": "tin tuyển dụng"},
                  "chunk_metadata": {"route_id": "R1"}},
        source_file=None,
        line_start=None,
        line_end=None,
    )
    out = _format_knowledge_row(row)
    # quote on the lead line, summary on the next, citation suffix indented
    assert out.startswith("- Lương 15 triệu\n")
    assert "Tóm tắt: Mô tả ngắn" in out
    assert "Nguồn: JD" in out
    assert "route_id: R1" in out


def test_format_row_falls_back_to_content_with_no_quote():
    row = SimpleNamespace(
        content="Nội dung thô",
        source_quote=None,
        summary=None,
        metadata={},
        source_file="policy.pdf",
        line_start=42,
        line_end=42,
    )
    out = _format_knowledge_row(row)
    assert "- Nội dung thô" in out
    assert "file: policy.pdf" in out
    assert "dòng: 42" in out
    # a single line range is not rendered as a 42-42 span
    assert "42-42" not in out


def test_format_row_renders_line_range_when_distinct():
    row = SimpleNamespace(
        content="x",
        source_quote=None,
        summary=None,
        metadata={},
        source_file=None,
        line_start=10,
        line_end=13,
    )
    assert "dòng: 10-13" in _format_knowledge_row(row)


def test_format_row_marks_effective_window():
    row = SimpleNamespace(
        content="x",
        source_quote="q",
        summary=None,
        metadata={"document_metadata": {"effective_from": "2026-01-01",
                                        "effective_to": "2026-06-01"}},
        source_file=None,
        line_start=None,
        line_end=None,
    )
    assert "hiệu lực: 2026-01-01 đến 2026-06-01" in _format_knowledge_row(row)


# ---------------------------------------------------------------------------
# search_user_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_user_memory_empty_returns_fixed_notice(no_cache_io, monkeypatch):
    _install_repo(
        monkeypatch,
        match_memories=lambda self, emb, top_k, filt_json: _empty(),
    )
    out = await search_user_memory(db=object(), embedder=_FakeEmbedder(),
                                   chat_id="c1", query="hi")
    assert out == "Không có thông tin ghi nhớ về người dùng này."


@pytest.mark.asyncio
async def test_search_user_memory_formats_rows_with_similarity(no_cache_io, monkeypatch):
    rows = [SimpleNamespace(content="đã làm lái xe 5 năm", similarity=0.91),
            SimpleNamespace(content="sống Bình Dương", similarity=0.82)]
    _install_repo(monkeypatch, match_memories=lambda self, *a, **k: _const(rows))
    out = await search_user_memory(db=object(), embedder=_FakeEmbedder(),
                                   chat_id="c1", query="kinh nghiệm")
    assert "đã làm lái xe 5 năm (sim=0.91)" in out
    assert "sống Bình Dương (sim=0.82)" in out
    assert out.count("\n") == 1  # two rows joined by a single newline


# ---------------------------------------------------------------------------
# list_active_projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_projects_empty(no_cache_io, monkeypatch):
    _install_repo(monkeypatch, list_active_projects=lambda self: _empty())
    out = await list_active_projects(db=object())
    assert out == "Hiện chưa có dự án/sản phẩm nào đang hoạt động."


@pytest.mark.asyncio
async def test_list_active_projects_formats_catalog(no_cache_io, monkeypatch):
    rows = [SimpleNamespace(slug="tai-xe", name="Tài xế", summary="Tuyển tài xế"),
            SimpleNamespace(slug="khac", name="Khác", summary=None)]
    _install_repo(monkeypatch, list_active_projects=lambda self: _const(rows))
    out = await list_active_projects(db=object())
    assert "- tai-xe (Tài xế): Tuyển tài xế" in out
    assert "- khac (Khác)" in out  # no summary → no trailing colon block


# ---------------------------------------------------------------------------
# search_knowledge — unknown slug short-circuits before embeddings/cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_knowledge_unknown_slug_returns_not_found(no_cache_io, monkeypatch):
    _install_repo(monkeypatch, project_id_by_slug=lambda self, slug, **k: _none())
    embedder = _FakeEmbedder()
    out = await search_knowledge(db=object(), embedder=embedder,
                                 query="lương", project_slug="khong-ton-tai")
    assert out == "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
    assert embedder.calls == []  # never embedded — slug miss is cheap


# ---------------------------------------------------------------------------
# get_product_features — unknown slug / empty / missing-flag rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_product_features_unknown_slug(no_cache_io, monkeypatch):
    _install_repo(monkeypatch, project_id_by_slug=lambda self, slug, **k: _none())
    out = await get_product_features(db=object(), project_slug="x")
    assert "Không tìm thấy dự án/sản phẩm với slug 'x'" in out


@pytest.mark.asyncio
async def test_get_product_features_empty_notice(no_cache_io, monkeypatch):
    _install_repo(
        monkeypatch,
        project_id_by_slug=lambda self, slug, **k: _const(7),
        job_features_for_project=lambda self, pid: _empty(),
    )
    out = await get_product_features(db=object(), project_slug="tai-xe")
    assert "Chưa có đặc điểm sản phẩm" in out


@pytest.mark.asyncio
async def test_get_product_features_flags_missing_and_highlight(no_cache_io, monkeypatch):
    rows = [
        SimpleNamespace(name_vi="Lương", value_text="15tr",
                        is_missing=True, needs_clarification=False, is_highlight=False),
        SimpleNamespace(name_vi="Chế độ", value_text="BHXH",
                        is_missing=False, needs_clarification=False, is_highlight=True),
        SimpleNamespace(name_vi="Thưởng", value_text="theo quý",
                        is_missing=False, needs_clarification=False, is_highlight=False),
    ]
    _install_repo(
        monkeypatch,
        project_id_by_slug=lambda self, slug, **k: _const(7),
        job_features_for_project=lambda self, pid: _const(rows),
    )
    out = await get_product_features(db=object(), project_slug="tai-xe")
    assert "Lương: 15tr [CHƯA RÕ" in out
    assert "Chế độ: BHXH [NỔI BẬT]" in out
    assert "Thưởng: theo quý" in out
    assert "QUY TẮC:" in out  # the "advise only from data" rule is always appended


# ---------------------------------------------------------------------------
# search_bus_timetable — grouping by (company, route, shift, direction)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_bus_timetable_groups_stops_under_route(no_cache_io, monkeypatch):
    rows = [
        SimpleNamespace(_mapping={
            "company_name": "VFIC", "route_name": "Bình Dương – Tây Ninh",
            "shift": "Sáng", "direction": "Chiều đi",
            "stop_name": "Bến xe", "scheduled_time": "05:30",
        }),
        SimpleNamespace(_mapping={
            "company_name": "VFIC", "route_name": "Bình Dương – Tây Ninh",
            "shift": "Sáng", "direction": "Chiều đi",
            "stop_name": "Ngã tư", "scheduled_time": "05:50",
        }),
        SimpleNamespace(_mapping={
            "company_name": "VFIC", "route_name": "Bình Dương – Tây Ninh",
            "shift": "Sáng", "direction": "Chiều đi",
            "stop_name": "Không giờ", "scheduled_time": "",
        }),
    ]
    _install_repo(
        monkeypatch,
        search_bus_timetable=lambda self, company, question, limit: _const(rows),
    )
    out = await search_bus_timetable(db=object(), company="VFIC", question="giờ chạy")
    # one route group collapses onto a single line; every stop is on that line
    assert "\n" not in out
    assert "Tuyến Bình Dương – Tây Ninh (Sáng/Chiều đi)" in out
    assert "Bến xe: 05:30" in out
    assert "Ngã tư: 05:50" in out
    assert "Không giờ: chưa có giờ trong nguồn" in out


@pytest.mark.asyncio
async def test_search_bus_timetable_no_rows_returns_notice(no_cache_io, monkeypatch):
    # second call (empty-company fallback) also empty → notice
    _install_repo(
        monkeypatch,
        search_bus_timetable=lambda self, company, question, limit: _empty(),
    )
    out = await search_bus_timetable(db=object(), company="VFIC", question="x")
    assert out == "Không tìm thấy lịch xe phù hợp."


# ---------------------------------------------------------------------------
# tiny async helpers (keep the lambda fake bodies one-liners)
# ---------------------------------------------------------------------------


async def _empty():
    return []


async def _const(value):
    return value


async def _none():
    return None
