"""Characterization tests for graph/tools.py — the agent's retrieval tool layer.

These pin two things that every graph-layer refactor must preserve:

* the ``TOOLS_REGISTRY`` contract (a tool cannot silently disappear or rename),
* the Vietnamese formatting + empty / not-found branch behavior of each tool.

No DB, embeddings, Redis, or LLM: a fake embedder + a fake ``RetrievalRepository``
stand in for the outside world. These are characterization tests — they pin
*current* behavior so refactors stay behavior-preserving.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.graph import tools
from app.graph.grounding import extract_surfaced_job_ids
from app.graph.tools import (
    TOOLS_REGISTRY,
    _format_knowledge_row,
    get_product_features,
    list_active_jobs,
    list_active_projects,
    recommend_projects,
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


def _make_repo(**methods):
    """Build a fake RetrievalPort with the given async methods (each ``self, ...``).

    Methods are set on the class so they bind as bound methods; the returned
    instance is passed straight to a tool as its ``retrieval`` argument.
    """

    class _Repo:
        pass

    for name, fn in methods.items():
        setattr(_Repo, name, fn)

    return _Repo()


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
        "list_active_jobs",
        "list_active_projects",
        "recommend_projects",
        "recommend_jobs",
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
        metadata={
            "citation": {"label": "JD"},
            "document_metadata": {"title": "tin tuyển dụng"},
            "chunk_metadata": {"route_id": "R1"},
        },
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
        metadata={
            "document_metadata": {"effective_from": "2026-01-01", "effective_to": "2026-06-01"}
        },
        source_file=None,
        line_start=None,
        line_end=None,
    )
    assert "hiệu lực: 2026-01-01 đến 2026-06-01" in _format_knowledge_row(row)


# ---------------------------------------------------------------------------
# search_user_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_user_memory_empty_returns_fixed_notice(no_cache_io):
    repo = _make_repo(match_memories=lambda self, emb, top_k, filt_json: _empty())
    out = await search_user_memory(
        retrieval=repo, embedder=_FakeEmbedder(), chat_id="c1", query="hi"
    )
    assert out == "Không có thông tin ghi nhớ về người dùng này."


@pytest.mark.asyncio
async def test_search_user_memory_formats_rows_with_similarity(no_cache_io):
    rows = [
        SimpleNamespace(content="đã làm lái xe 5 năm", similarity=0.91),
        SimpleNamespace(content="sống Bình Dương", similarity=0.82),
    ]
    repo = _make_repo(match_memories=lambda self, *a, **k: _const(rows))
    out = await search_user_memory(
        retrieval=repo, embedder=_FakeEmbedder(), chat_id="c1", query="kinh nghiệm"
    )
    assert out.startswith("NGỮ CẢNH RIÊNG TƯ")
    assert "Không được trích dẫn, tóm tắt" in out
    assert "đã làm lái xe 5 năm (sim=0.91)" in out
    assert "sống Bình Dương (sim=0.82)" in out
    assert out.count("\n") == 2  # privacy notice + two rows


# ---------------------------------------------------------------------------
# list_active_jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_jobs_forwards_explicit_filters_and_bounds_top_k(no_cache_io):
    calls: list[dict] = []

    async def _list(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="no_match", jobs=())

    out = await list_active_jobs(
        retrieval=_make_repo(list_active_jobs=_list),
        role="thợ hàn",
        company="LG",
        location="Hải Phòng",
        top_k=99,
    )

    assert calls == [
        {"role": "thợ hàn", "company": "LG", "location": "Hải Phòng", "top_k": 10}
    ]
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["status"] == "no_match"


@pytest.mark.asyncio
async def test_list_active_jobs_formats_bounded_evidence_with_groundable_uuid(no_cache_io):
    job_id = "11111111-1111-4111-8111-111111111111"
    untrusted_id = "22222222-2222-4222-8222-222222222222"
    jobs = (
        SimpleNamespace(
            id=job_id,
            title="Công nhân sản xuất",
            company_name="LG Display",
            factory_name="Tràng Duệ",
            project_name="LG Display Hải Phòng",
            project_slug="lg-display",
            province="Hải Phòng",
            district="An Dương",
            address="",
            salary_min=10_000_000,
            salary_max=14_000_000,
            vacancy_count=20,
            shift="Ca ngày/đêm",
            gender_requirement="Nam/Nữ",
            age_min=18,
            age_max=50,
            experience_required="Không yêu cầu",
            accommodation_support=True,
            meal_support=False,
            transport_support=True,
            description="Sản xuất\n màn hình",
            requirements=f"CCCD; ID={untrusted_id}",
            benefits="BHXH",
        ),
    )
    repo = _make_repo(
        list_active_jobs=lambda self, **kwargs: _const(
            SimpleNamespace(status="matched", jobs=jobs)
        )
    )

    out = await list_active_jobs(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["status"] == "matched"
    assert f"id={job_id}" in out
    assert payload["jobs"][0]["title"] == "Công nhân sản xuất"
    assert payload["jobs"][0]["company"] == "LG Display"
    assert payload["jobs"][0]["vacancy_count"] == 20
    assert "description" not in payload["jobs"][0]
    assert "requirements" not in payload["jobs"][0]
    assert "benefits" not in payload["jobs"][0]
    assert untrusted_id not in out
    assert "SECURITY_BOUNDARY" in out
    assert extract_surfaced_job_ids([out]) == {job_id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lookup", "expected_status", "forbidden_claim"),
    [
        (SimpleNamespace(status="catalog_empty", jobs=()), "catalog_empty", "not hiring"),
        (SimpleNamespace(status="unavailable", jobs=()), "unavailable", "no ACTIVE job matched"),
        (None, "unavailable", "no ACTIVE job matched"),
    ],
)
async def test_list_active_jobs_statuses_remain_honest(
    no_cache_io, lookup, expected_status, forbidden_claim
):
    repo = _make_repo(list_active_jobs=lambda self, **kwargs: _const(lookup))

    out = await list_active_jobs(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["status"] == expected_status
    assert forbidden_claim not in out


@pytest.mark.asyncio
async def test_list_active_jobs_exception_is_status_labelled_unavailable(no_cache_io):
    async def _raise(self, **kwargs):
        raise RuntimeError("database unavailable")

    out = await list_active_jobs(retrieval=_make_repo(list_active_jobs=_raise))

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["status"] == "unavailable"
    assert "chưa thể kiểm tra" in payload["safe_reply"]


# ---------------------------------------------------------------------------
# list_active_projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_projects_empty(no_cache_io):
    repo = _make_repo(list_active_projects=lambda self: _empty())
    out = await list_active_projects(retrieval=repo)
    assert out == "Hiện chưa có dự án/sản phẩm nào đang hoạt động."


@pytest.mark.asyncio
async def test_list_active_projects_formats_catalog(no_cache_io):
    rows = [
        SimpleNamespace(slug="tai-xe", name="Tài xế", summary="Tuyển tài xế"),
        SimpleNamespace(slug="khac", name="Khác", summary=None),
    ]
    repo = _make_repo(list_active_projects=lambda self: _const(rows))
    out = await list_active_projects(retrieval=repo)
    assert "- tai-xe (Tài xế): Tuyển tài xế" in out
    assert "- khac (Khác)" in out  # no summary → no trailing colon block


# ---------------------------------------------------------------------------
# recommend_projects — deterministic recommendation seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_projects_empty_catalog(no_cache_io):
    repo = _make_repo(active_projects_with_card=lambda self: _empty())
    out = await recommend_projects(retrieval=repo, query="gợi ý việc")
    assert out == "Hiện chưa có dự án/sản phẩm nào đang hoạt động để gợi ý."


@pytest.mark.asyncio
async def test_recommend_projects_ranks_by_catalog_terms(no_cache_io):
    rows = [
        SimpleNamespace(
            slug="lg-display",
            name="LG Display",
            summary="Tuyển công nhân sản xuất tại Hải Phòng",
            index_card={"key_roles": ["công nhân sản xuất"], "location": "Hải Phòng"},
        ),
        SimpleNamespace(
            slug="kho-binh-duong",
            name="Kho Bình Dương",
            summary="Tuyển kho vận có ký túc xá",
            index_card={"key_roles": ["nhân viên kho"], "location": "Bình Dương"},
        ),
    ]
    repo = _make_repo(active_projects_with_card=lambda self: _const(rows))

    out = await recommend_projects(
        retrieval=repo,
        query="Tôi muốn việc kho ở Bình Dương có ký túc xá",
        top_k=2,
    )

    first_line = out.splitlines()[1]
    assert first_line.startswith("- kho-binh-duong")
    assert "lý do:" in first_line
    assert "binh" in first_line or "duong" in first_line
    assert "get_product_features(project_slug)" in out


@pytest.mark.asyncio
async def test_recommend_projects_rejects_substring_only_matches(no_cache_io):
    """`tho`/`han` must not match unrelated `thong`/`nhan` catalog text."""
    rows = [
        SimpleNamespace(
            slug="lg-display",
            name="LG Display",
            summary="Lao động phổ thông",
            index_card={"key_roles": ["lao động phổ thông", "nhân viên sản xuất"]},
        )
    ]
    repo = _make_repo(active_projects_with_card=lambda self: _const(rows))

    out = await recommend_projects(retrieval=repo, query="bên bạn tuyển thợ hàn CO2 đúng ko?")

    assert out.startswith("Không có dự án trong danh mục phù hợp")
    assert "đang tuyển" in out


# ---------------------------------------------------------------------------
# search_knowledge — unknown slug short-circuits before embeddings/cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_knowledge_unknown_slug_returns_not_found(no_cache_io):
    repo = _make_repo(project_id_by_slug=lambda self, slug, **k: _none())
    embedder = _FakeEmbedder()
    out = await search_knowledge(
        retrieval=repo, embedder=embedder, query="lương", project_slug="khong-ton-tai"
    )
    assert out == "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
    assert embedder.calls == []  # never embedded — slug miss is cheap


# ---------------------------------------------------------------------------
# get_product_features — unknown slug / empty / missing-flag rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_product_features_unknown_slug(no_cache_io):
    repo = _make_repo(project_id_by_slug=lambda self, slug, **k: _none())
    out = await get_product_features(retrieval=repo, project_slug="x")
    assert "Không tìm thấy dự án/sản phẩm với slug 'x'" in out


@pytest.mark.asyncio
async def test_get_product_features_empty_notice(no_cache_io):
    repo = _make_repo(
        project_id_by_slug=lambda self, slug, **k: _const(7),
        job_features_for_project=lambda self, pid: _empty(),
    )
    out = await get_product_features(retrieval=repo, project_slug="tai-xe")
    assert "Chưa có đặc điểm sản phẩm" in out


@pytest.mark.asyncio
async def test_get_product_features_flags_missing_and_highlight(no_cache_io):
    rows = [
        SimpleNamespace(
            name_vi="Lương",
            value_text="15tr",
            is_missing=True,
            needs_clarification=False,
            is_highlight=False,
        ),
        SimpleNamespace(
            name_vi="Chế độ",
            value_text="BHXH",
            is_missing=False,
            needs_clarification=False,
            is_highlight=True,
        ),
        SimpleNamespace(
            name_vi="Thưởng",
            value_text="theo quý",
            is_missing=False,
            needs_clarification=False,
            is_highlight=False,
        ),
    ]
    repo = _make_repo(
        project_id_by_slug=lambda self, slug, **k: _const(7),
        job_features_for_project=lambda self, pid: _const(rows),
    )
    out = await get_product_features(retrieval=repo, project_slug="tai-xe")
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
        SimpleNamespace(
            _mapping={
                "company_name": "VFIC",
                "route_name": "Bình Dương – Tây Ninh",
                "shift": "Sáng",
                "direction": "Chiều đi",
                "stop_name": "Bến xe",
                "scheduled_time": "05:30",
            }
        ),
        SimpleNamespace(
            _mapping={
                "company_name": "VFIC",
                "route_name": "Bình Dương – Tây Ninh",
                "shift": "Sáng",
                "direction": "Chiều đi",
                "stop_name": "Ngã tư",
                "scheduled_time": "05:50",
            }
        ),
        SimpleNamespace(
            _mapping={
                "company_name": "VFIC",
                "route_name": "Bình Dương – Tây Ninh",
                "shift": "Sáng",
                "direction": "Chiều đi",
                "stop_name": "Không giờ",
                "scheduled_time": "",
            }
        ),
    ]
    repo = _make_repo(
        search_bus_timetable=lambda self, company, question, limit: _const(rows),
    )
    out = await search_bus_timetable(retrieval=repo, company="VFIC", question="giờ chạy")
    # one route group collapses onto a single line; every stop is on that line
    assert "\n" not in out
    assert "Tuyến Bình Dương – Tây Ninh (Sáng/Chiều đi)" in out
    assert "Bến xe: 05:30" in out
    assert "Ngã tư: 05:50" in out
    assert "Không giờ: chưa có giờ trong nguồn" in out


@pytest.mark.asyncio
async def test_search_bus_timetable_no_rows_returns_notice(no_cache_io):
    # second call (empty-company fallback) also empty → notice
    repo = _make_repo(
        search_bus_timetable=lambda self, company, question, limit: _empty(),
    )
    out = await search_bus_timetable(retrieval=repo, company="VFIC", question="x")
    assert out == "Không tìm thấy lịch xe phù hợp."


# ---------------------------------------------------------------------------
# recommend_jobs — structured Job↔Lead recommendation (Phase 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_jobs_empty_returns_fallback_notice(no_cache_io):
    """Missing profile is distinct from no ACTIVE match and an outage."""
    from app.services.recommendation import LeadJobRecommendation

    repo = _make_repo(
        recommend_jobs_for_lead=lambda self, chat_id, **k: _const(
            LeadJobRecommendation("insufficient_profile")
        )
    )
    out = await tools.recommend_jobs(retrieval=repo, chat_id="z1")
    assert "Chưa đủ thông tin hồ sơ" in out


@pytest.mark.asyncio
async def test_recommend_jobs_formats_scored_results_with_reasons(no_cache_io):
    """Scored jobs render as a grounded shortlist with matched reasons."""
    from app.services.recommendation.scoring import JobCandidate, ScoredJob

    scored = [
        ScoredJob(
            job=JobCandidate(
                id="job-1",
                title="Nhân viên kho",
                province="Bình Dương",
                salary_min=10_000_000,
                salary_max=14_000_000,
            ),
            score=0.82,
            reasons=["vị trí khớp mong muốn", "lương 10-14 triệu phù hợp"],
        ),
    ]
    from app.services.recommendation import LeadJobRecommendation

    repo = _make_repo(
        recommend_jobs_for_lead=lambda self, chat_id, **k: _const(
            LeadJobRecommendation("matched", tuple(scored))
        )
    )
    out = await tools.recommend_jobs(retrieval=repo, chat_id="z1")
    assert "GỢI Ý VIỆC LÀM PHÙ HỢP" in out
    assert "Nhân viên kho" in out
    assert "job-1" in out
    assert "10-14 triệu" in out
    assert "điểm phù hợp: 0.82" in out
    assert "QUY TẮC:" in out  # grounding rule always appended


@pytest.mark.asyncio
async def test_recommend_jobs_exception_returns_fallback_not_crash(no_cache_io):
    """A retrieval failure must never be represented as a missing vacancy."""

    async def _boom(self, chat_id, **k):
        raise RuntimeError("db down")

    repo = _make_repo(recommend_jobs_for_lead=_boom)
    out = await tools.recommend_jobs(retrieval=repo, chat_id="z1")
    assert "chưa thể tra cứu" in out.lower()
    assert "chưa có việc" not in out.lower()


@pytest.mark.asyncio
async def test_recommend_jobs_no_match_is_distinct_from_unavailable(no_cache_io):
    from app.services.recommendation import LeadJobRecommendation

    repo = _make_repo(
        recommend_jobs_for_lead=lambda self, chat_id, **k: _const(LeadJobRecommendation("no_match"))
    )

    out = await tools.recommend_jobs(retrieval=repo, chat_id="z1")

    assert out == "Hiện chưa có việc làm ACTIVE phù hợp với hồ sơ này."


# ---------------------------------------------------------------------------
# tiny async helpers (keep the lambda fake bodies one-liners)
# ---------------------------------------------------------------------------


async def _empty():
    return []


async def _const(value):
    return value


async def _none():
    return None


# ---------------------------------------------------------------------------
# search_knowledge — RAG cache telemetry (metrics threading)
# ---------------------------------------------------------------------------


@pytest.fixture
def cache_enabled_io(monkeypatch):
    """Enable RAG exact-hash caching with controllable fakes (no live Redis).

    Mirrors ``no_cache_io`` but flips ``rag_cache_enabled = True`` and lets the
    test inject the exact-cache return value via ``exact_cache_value``.
    """

    class _S:
        rag_cache_enabled = True
        semantic_cache_enabled = False
        embedding_provider = "openrouter"
        openrouter_embedding_model = "openai/text-embedding-3-large"
        gemini_embedding_model = "gemini-embedding-2"
        embedding_dim = 8
        embedding_cache_ttl_seconds = 60
        rag_result_cache_ttl_seconds = 60

    monkeypatch.setattr(tools, "get_settings", lambda: _S())

    state = {"exact": None}

    async def _fake_get(key):
        return state["exact"]

    async def _noop_set(*a, **k):
        return None

    async def _noop_version(*a, **k):
        return "0"

    monkeypatch.setattr(tools, "cache_get_json", _fake_get)
    monkeypatch.setattr(tools, "cache_set_json", _noop_set)
    monkeypatch.setattr(tools, "cache_version", _noop_version)
    return state


@pytest.mark.asyncio
async def test_search_knowledge_records_exact_cache_hit(cache_enabled_io):
    """When the exact-hash RAG cache returns a string, telemetry records the hit."""
    cache_enabled_io["exact"] = "Lương cơ bản 15 triệu/tháng."
    repo = _make_repo()
    embedder = _FakeEmbedder()
    metrics: dict = {}

    out = await search_knowledge(
        retrieval=repo, embedder=embedder, query="lương", metrics=metrics
    )

    assert out == "Lương cơ bản 15 triệu/tháng."
    assert metrics["rag_cache"]["exact_hit"] is True
    assert metrics["rag_cache"]["semantic_hit"] is False
    assert metrics["rag_cache_lookup_ms"] >= 0
    # Embedder must NOT be called on an exact-cache hit (the whole point).
    assert embedder.calls == []


@pytest.mark.asyncio
async def test_search_knowledge_records_cache_miss_when_disabled(no_cache_io):
    """With caching disabled, telemetry records explicit misses (not absence).

    An explicit ``False`` lets dashboard queries distinguish "no lookup" from
    "lookup missed"; absence is ambiguous.
    """
    repo = _make_repo(
        match_faq=lambda self, emb, *, top_k, project_ids: _const([]),
        match_documents=lambda self, emb, top_k, *_a, **_k: _const([]),
    )
    metrics: dict = {}

    out = await search_knowledge(
        retrieval=repo, embedder=_FakeEmbedder(), query="lương", metrics=metrics
    )

    assert "Không tìm thấy" in out
    assert metrics["rag_cache"]["exact_hit"] is False
    assert metrics["rag_cache"]["semantic_hit"] is False
    assert metrics["rag_cache_lookup_ms"] >= 0


@pytest.mark.asyncio
async def test_search_knowledge_no_metrics_is_backward_compatible(no_cache_io):
    """Omitting ``metrics`` must not raise and must not change the return value."""
    repo = _make_repo(
        match_faq=lambda self, emb, *, top_k, project_ids: _const([]),
        match_documents=lambda self, emb, top_k, *_a, **_k: _const([]),
    )

    out = await search_knowledge(
        retrieval=repo, embedder=_FakeEmbedder(), query="lương"
    )

    assert "Không tìm thấy" in out
