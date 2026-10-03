# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportTypedDictNotRequiredAccess=false, reportOptionalSubscript=false, reportOptionalMemberAccess=false, reportReturnType=false, reportOptionalOperand=false, reportOptionalCall=false, reportOperatorIssue=false, reportIndexIssue=false
#
# Typed-double convention (mirrors test_graph_runner_turn.py and
# test_integration_settings.py, issue #39 option b): the stubs here
# (_FakeEmbedder, _Repo, SimpleNamespace rows) deliberately implement only the
# narrow duck-typed surface each tool exercises, so every retrieval= hand-off
# trips reportArgumentType/reportAttributeAccessIssue and the outcome
# assertions index optional TypedDict keys. Casting ~110 sites would add noise,
# not safety — the real gate is the behavioral suite below.
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
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.core.vector import pack_vector, unpack_vector
from app.graph import embed_cache, tools
from app.graph.grounding import extract_surfaced_ids
from app.recruitment.domain.recommendation import (
    ActiveProjectIncomeSummary,
    IncomeFeatureEvidence,
    ProjectFeatures,
    ProjectScopeItem,
)
from app.graph.tools import (
    TOOLS_REGISTRY,
    _format_knowledge_row,
    compare_income,
    get_product_features,
    list_active_projects,
    search_bus_timetable,
    search_knowledge,
    search_user_memory,
)
from app.graph.income_contract import IncomeVerdict
from app.graph.tools.catalog import (
    _CATALOG_EMPTY_REPLY,
    _NO_CRITERIA_REPLY,
    _PRESENTATION_CONTRACT,
    get_project_distance,
)

# The tools package splits tool logic into domain modules; each holds its own
# module-level binding of get_settings/cache helpers, so the cache fixtures
# below patch every submodule (not just the package attribute).
_TOOL_MODULES = tuple(
    getattr(tools, name)
    for name in ("_shared", "memory", "knowledge", "income", "catalog")
)


def _patch_tool_io(monkeypatch, settings_cls, **cache_overrides):
    """Apply fake settings + fake cache IO to every tool submodule."""
    async def _noop_get(*_a, **_k):
        return None

    async def _noop_set(*_a, **_k):
        return None

    async def _noop_version(*_a, **_k):
        return "0"

    for module in _TOOL_MODULES:
        monkeypatch.setattr(module, "get_settings", lambda: settings_cls(), raising=False)
        monkeypatch.setattr(
            module, "cache_get_json", cache_overrides.get("get", _noop_get), raising=False
        )
        monkeypatch.setattr(
            module, "cache_set_json", cache_overrides.get("set", _noop_set), raising=False
        )
        monkeypatch.setattr(
            module, "cache_version", cache_overrides.get("version", _noop_version), raising=False
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
    """Build a fake GraphRetrievalPort with the given async methods (each ``self, ...``).

    Methods are set on the class so they bind as bound methods; the returned
    instance is passed straight to a tool as its ``retrieval`` argument.
    """

    class _Repo:
        pass

    for name, fn in methods.items():
        setattr(_Repo, name, fn)

    return _Repo()


_ORIGIN = (20.86, 106.68)


def _geo_area(origin=_ORIGIN, *, calls: list[str] | None = None):
    """A ``geocode_area`` port method returning ``origin`` and recording queries."""

    async def geocode_area(self, query):
        if calls is not None:
            calls.append(query)
        return origin

    return geocode_area


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

    _patch_tool_io(monkeypatch, _S)
    return _S()


# ---------------------------------------------------------------------------
# Registry contract
# ---------------------------------------------------------------------------


def test_tools_registry_exposes_expected_tools():
    """No tool silently disappears/renames during a refactor (F-CRIT-2 guard)."""
    assert set(TOOLS_REGISTRY) == {
        "compare_income",
        "search_user_memory",
        "search_knowledge",
        "load_project_knowledge",
        "list_active_projects",
        "get_project_distance",
        "search_bus_timetable",
        "get_product_features",
        "verify_tingting_identity",
        "send_tingting_otp",
        "confirm_tingting_otp",
        "reset_tingting_password",
    }
    assert all(callable(fn) for fn in TOOLS_REGISTRY.values())


@pytest.mark.asyncio
async def test_compare_income_formats_threshold_evidence(no_cache_io):
    repo = _make_repo(
        income_summary_for_active_projects=lambda self: _const(
            (
                ActiveProjectIncomeSummary(
                    project_id="p1",
                    project_slug="lg-display",
                    project_name="LG Display",
                    evidence=(
                        IncomeFeatureEvidence(
                            feature_key="take_home_income",
                            category="income",
                            name_vi="Thu nhập",
                            value_text="Thu nhập thực tế 10-13 triệu/tháng khi có tăng ca, chưa bao gồm thưởng.",
                        ),
                    ),
                ),
                ActiveProjectIncomeSummary(
                    project_id="p2",
                    project_slug="rorze",
                    project_name="Rorze",
                    evidence=(
                        IncomeFeatureEvidence(
                            feature_key="salary_transparency",
                            category="income",
                            name_vi="Dữ liệu cũ",
                            value_text="Không dùng dòng chưa xác minh này.",
                            is_missing=True,
                        ),
                        IncomeFeatureEvidence(
                            feature_key="take_home_income",
                            category="income",
                            name_vi="Thu nhập",
                            value_text=(
                                "Thu nhập trung bình thực nhận theo tháng (có OVT, chưa bao gồm "
                                "thưởng): 14-15 triệu/tháng. Thu nhập trung bình theo năm (bao "
                                "gồm thưởng): 20-21 triệu/tháng."
                            ),
                        ),
                        IncomeFeatureEvidence(
                            feature_key="salary_transparency",
                            category="income",
                            name_vi="Cách công bố",
                            value_text="Công bố riêng thu nhập tháng và bình quân năm.",
                        ),
                        IncomeFeatureEvidence(
                            feature_key="overtime_rate",
                            category="income",
                            name_vi="Tăng ca",
                            value_text="Thu nhập tháng có OVT.",
                        ),
                        IncomeFeatureEvidence(
                            feature_key="joining_bonus",
                            category="bonus",
                            name_vi="Thưởng",
                            value_text="Thưởng được tính trong bình quân năm.",
                        ),
                        IncomeFeatureEvidence(
                            feature_key="pay_frequency",
                            category="cashflow",
                            name_vi="Kỳ lương",
                            value_text="Chốt công từ ngày 01 đến cuối tháng, trả lương ngày 10 tháng sau.",
                        ),
                    ),
                ),
            )
        )
    )

    out = await compare_income(retrieval=repo, target_monthly_vnd=20_000_000)

    assert isinstance(out, IncomeVerdict)
    assert out.status == "matched"
    assert out.target_monthly_vnd == 20_000_000
    payload = out.projects
    first_row = cast(dict[str, Any], payload[0])
    assert first_row["project_slug"] == "rorze"
    assert "comparison" not in first_row
    assert "comparison" not in payload[1]
    assert "14-15 triệu/tháng" in out
    assert "20-21 triệu/tháng" in out
    assert "Kỳ lương" in out
    assert [item["feature_key"] for item in first_row["evidence"]] == [
        "take_home_income",
        "salary_transparency",
        "overtime_rate",
        "joining_bonus",
        "pay_frequency",
    ]
    assert "Không dùng dòng chưa xác minh này." not in out
    assert "chưa thấy bằng chứng đạt mốc" not in out
    assert "chưa có vị trí nào" not in out
    assert "SECURITY_BOUNDARY" in out


@pytest.mark.asyncio
async def test_compare_income_ranks_target_evidence_before_project_cap(no_cache_io):
    summaries = tuple(
        ActiveProjectIncomeSummary(
            project_id=f"p{index}",
            project_slug=f"project-{index:02d}",
            project_name=f"Project {index:02d}",
            evidence=(
                IncomeFeatureEvidence(
                    feature_key="take_home_income",
                    category="income",
                    name_vi="Thu nhập",
                    value_text="Khoảng 10-13 triệu/tháng.",
                ),
            ),
        )
        for index in range(21)
    ) + (
        ActiveProjectIncomeSummary(
            project_id="rorze",
            project_slug="rorze",
            project_name="Rorze",
            evidence=(
                IncomeFeatureEvidence(
                    feature_key="take_home_income",
                    category="income",
                    name_vi="Thu nhập",
                    value_text="14-15 triệu/tháng chưa gồm thưởng; 20-21 triệu/tháng gồm thưởng.",
                ),
            ),
        ),
    )
    repo = _make_repo(
        income_summary_for_active_projects=lambda self: _const(summaries)
    )

    out = await compare_income(retrieval=repo, target_monthly_vnd=20_000_000)

    payload = out.projects
    assert len(payload) == 20
    assert payload[0]["project_slug"] == "rorze"


@pytest.mark.asyncio
async def test_compare_income_reports_retrieval_failure_as_unavailable(no_cache_io):
    async def fail(self):
        raise RuntimeError("database unavailable")

    out = await compare_income(
        retrieval=_make_repo(income_summary_for_active_projects=fail),
        target_monthly_vnd=20_000_000,
    )

    assert out.status == "unavailable"
    assert out.projects == []
    assert "chưa thể kiểm tra dữ liệu thu nhập" in out.safe_reply
    assert "chưa có dữ liệu thu nhập" not in out.safe_reply


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
# list_active_projects — the project-first matching authority
# ---------------------------------------------------------------------------


def _features(
    index: int,
    *,
    name: str = "",
    company: str = "",
    province: str = "",
    salary_min: int | None = None,
    salary_max: int | None = None,
    scope: tuple[ProjectScopeItem, ...] = (),
) -> ProjectFeatures:
    return ProjectFeatures(
        project_id=f"{index:08x}-1111-4111-8111-111111111111",
        slug=f"project-{index}",
        name=name or f"Dự án {index}",
        company=company,
        province=province,
        salary_min=salary_min,
        salary_max=salary_max,
        scope=scope,
    )


def _rorze() -> ProjectFeatures:
    """A Rorze-like project: two scope roles, Hải Phòng, 6,3-10 triệu."""
    return ProjectFeatures(
        project_id="aaaaaaaa-1111-4111-8111-111111111111",
        slug="rorze",
        name="Rorze",
        company="Rorze",
        province="Hải Phòng",
        salary_min=6_300_000,
        salary_max=10_000_000,
        scope=(
            ProjectScopeItem("Nhân viên lắp ráp", 6_300_000, 10_000_000),
            ProjectScopeItem("Nhân viên vận hành máy CNC", 7_000_000, 11_000_000),
        ),
    )


def _catalog() -> list[ProjectFeatures]:
    """Twelve projects — sized to regress the old top_k=10 truncation."""
    return [_rorze()] + [_features(index) for index in range(2, 13)]


@pytest.mark.asyncio
async def test_list_active_projects_empty_catalog_reports_catalog_empty(no_cache_io):
    repo = _make_repo(list_active_projects=lambda self: _empty())
    out = await list_active_projects(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "catalog_empty"
    assert payload["total"] == 0
    assert payload["projects"] == []
    assert payload["safe_reply"] == _CATALOG_EMPTY_REPLY
    assert "SURFACED_PROJECT_IDS" not in out
    assert "SECURITY_BOUNDARY" in out


@pytest.mark.asyncio
async def test_list_active_projects_surfaces_whole_catalog_without_truncation(no_cache_io):
    """The answer unit is the project: every project surfaces, never top_k-capped."""
    projects = _catalog()
    repo = _make_repo(list_active_projects=lambda self: _const(projects))

    out = await list_active_projects(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "matched"
    assert payload["total"] == 12
    assert len(payload["projects"]) == 12
    assert payload["safe_reply"] == _PRESENTATION_CONTRACT
    # Rule (8) is the only place the agent is told the distance answers "gần nhà".
    assert "(8) " in _PRESENTATION_CONTRACT
    assert "distance_km" in _PRESENTATION_CONTRACT
    surfaced_line = out.splitlines()[1]
    assert surfaced_line.count("id=") == 12
    assert set(surfaced_line.removeprefix("SURFACED_PROJECT_IDS=").split(",")) == {
        f"id={project.project_id}" for project in projects
    }


@pytest.mark.asyncio
async def test_list_active_projects_company_request_hard_filters_and_notes_fit(no_cache_io):
    repo = _make_repo(list_active_projects=lambda self: _const(_catalog()))

    out = await list_active_projects(retrieval=repo, company="rorze")

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "matched"
    assert payload["total"] == 1
    assert [row["slug"] for row in payload["projects"]] == ["rorze"]
    assert any("công ty" in note for note in payload["projects"][0]["fit_notes"])


@pytest.mark.asyncio
async def test_list_active_projects_unmatched_company_is_honest_empty(no_cache_io):
    """A named company that matches nothing is a matched empty list, not no_match."""
    repo = _make_repo(list_active_projects=lambda self: _const(_catalog()))

    out = await list_active_projects(retrieval=repo, company="không tồn tại")

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "matched"
    assert payload["total"] == 0
    assert payload["projects"] == []
    assert payload["safe_reply"].startswith(_NO_CRITERIA_REPLY)
    assert "SURFACED_PROJECT_IDS" not in out


@pytest.mark.asyncio
async def test_list_active_projects_unknown_slug_returns_not_found(no_cache_io):
    repo = _make_repo(list_active_projects=lambda self: _const(_catalog()))

    out = await list_active_projects(retrieval=repo, project_slug="nope")

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "matched"
    assert payload["total"] == 0
    assert payload["projects"] == []
    assert payload["safe_reply"] == "Không tìm thấy dự án với slug này."


@pytest.mark.asyncio
async def test_list_active_projects_focused_slug_keeps_only_that_project(no_cache_io):
    repo = _make_repo(list_active_projects=lambda self: _const(_catalog()))

    out = await list_active_projects(retrieval=repo, project_slug="rorze")

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "matched"
    assert payload["total"] == 1
    assert [row["slug"] for row in payload["projects"]] == ["rorze"]


@pytest.mark.asyncio
async def test_list_active_projects_fit_notes_cover_matches_gaps_and_glosses(no_cache_io):
    """Stated preferences score per dimension; notes render honestly and gloss jargon."""
    projects = [
        ProjectFeatures(
            project_id="aaaaaaaa-1111-4111-8111-111111111111",
            slug="rorze",
            name="Rorze",
            company="Rorze",
            province="Hải Phòng",
            salary_min=6_300_000,
            salary_max=10_000_000,
            scope=(
                ProjectScopeItem("Nhân viên lắp ráp", 6_300_000, 10_000_000),
                ProjectScopeItem("Kỹ thuật viên CNC", 7_000_000, 11_000_000),
            ),
        ),
        _features(3, name="Kho Unknown", province="Bình Dương"),
    ]
    repo = _make_repo(
        list_active_projects=lambda self: _const(projects), geocode_area=_geo_area()
    )

    out = await list_active_projects(
        retrieval=repo,
        job_scope="lắp ráp",
        location="Hải Phòng",
        salary_min_vnd=8_000_000,
    )

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    by_slug = {row["slug"]: row for row in payload["projects"]}
    rorze = by_slug["rorze"]
    assert rorze["fit_score"] == 1.0
    assert "lương 6,3-10 triệu" in " ".join(rorze["fit_notes"])
    assert all(note.endswith("· khớp") for note in rorze["fit_notes"])
    assert rorze["job_scope"][1]["title_plain"] == "Kỹ thuật viên CNC (máy gia công tinh)"
    assert any("máy gia công tinh" in item["title_plain"] for item in rorze["job_scope"])
    gap = by_slug["project-3"]
    assert "chưa ghi rõ lương" in gap["fit_notes"]
    assert "chưa ghi rõ phạm vi công việc" in gap["fit_notes"]


@pytest.mark.asyncio
async def test_list_active_projects_ignores_malformed_sort_and_salary_arguments(no_cache_io):
    repo = _make_repo(list_active_projects=lambda self: _const(_catalog()))

    out = await list_active_projects(
        retrieval=repo, sort_by="bogus", salary_min_vnd="10 triệu"
    )

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "matched"
    assert payload["total"] == 12


@pytest.mark.asyncio
async def test_list_active_projects_filters_only_when_strictly_requested(no_cache_io):
    repo = _make_repo(
        list_active_projects=lambda self: _const(_catalog()), geocode_area=_geo_area()
    )
    relaxed = await list_active_projects(retrieval=repo, location="Hải Phòng")
    strict = await list_active_projects(
        retrieval=repo, location="Hải Phòng", strict_criteria=True,
    )
    relaxed_payload = json.loads(relaxed.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    strict_payload = json.loads(strict.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert relaxed_payload["total"] == 12
    assert 0 < strict_payload["total"] < 12
    assert all(row["province"] == "Hải Phòng" for row in strict_payload["projects"])


@pytest.mark.asyncio
async def test_list_active_projects_does_not_coerce_string_true_into_strict_filter(
    no_cache_io
):
    repo = _make_repo(
        list_active_projects=lambda self: _const(_catalog()), geocode_area=_geo_area()
    )
    out = await list_active_projects(
        retrieval=repo, location="Hải Phòng", strict_criteria="false", salary_min_vnd=-1,
    )
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["total"] == 12
    assert all("lương" not in note for row in payload["projects"] for note in row["fit_notes"])


@pytest.mark.asyncio
async def test_list_active_projects_retrieval_failure_is_status_labelled_unavailable(
    no_cache_io,
):
    async def _raise(self):
        raise RuntimeError("database unavailable")

    out = await list_active_projects(retrieval=_make_repo(list_active_projects=_raise))

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert payload["status"] == "unavailable"
    assert payload["total"] == 0
    assert payload["projects"] == []
    assert payload["safe_reply"] == (
        "Hiện tôi chưa thể kiểm tra danh mục dự án. Bạn vui lòng thử lại sau nhé."
    )


@pytest.mark.asyncio
async def test_list_active_projects_surfaced_ids_match_payload_project_ids(no_cache_io):
    projects = _catalog()
    repo = _make_repo(list_active_projects=lambda self: _const(projects))

    out = await list_active_projects(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert extract_surfaced_ids([out]) == {row["id"] for row in payload["projects"]}
    assert extract_surfaced_ids([out]) == {project.project_id for project in projects}


# ---------------------------------------------------------------------------
# distance estimates — provider road numbers outrank straight-line, and the
# straight-line fallback survives every missing-method / all-None shape
# ---------------------------------------------------------------------------


def _geo_project(
    index: int, *, lat: float, lng: float, company: str = "AmTRAN"
) -> ProjectFeatures:
    """A project with geocoded coordinates — the shape distance needs."""
    return ProjectFeatures(
        project_id=f"{index:08x}-2222-4222-8222-222222222222",
        slug=f"geo-{index}",
        name=f"Geo {index}",
        company=company,
        province="Hải Phòng",
        latitude=lat,
        longitude=lng,
    )


def _estimates_factory(results, *, calls: list | None = None):
    """A ``estimate_distances_km`` port method returning ``results`` (aligned)."""

    async def estimate_distances_km(self, origin, destinations):
        if calls is not None:
            calls.append((origin, destinations))
        return list(results(origin, destinations)) if callable(results) else list(results)

    return estimate_distances_km


@pytest.mark.asyncio
async def test_list_active_projects_road_estimate_outranks_straight_line(no_cache_io):
    """The provider number is the number: it replaces ``distance_km`` and re-orders."""
    projects = [_geo_project(1, lat=20.90, lng=106.70), _geo_project(2, lat=21.20, lng=107.20)]
    calls: list = []
    # Straight-line: project 1 is far nearer. The road estimate flips it — a
    # bridge-less river crossing can do that — and the reply must follow road.
    repo = _make_repo(
        list_active_projects=lambda self: _const(projects),
        geocode_area=_geo_area(),
        estimate_distances_km=_estimates_factory(
            lambda _origin, _dests: [(30.0, 3600.0), (5.0, 600.0)], calls=calls
        ),
    )

    out = await list_active_projects(retrieval=repo, location="Hải Phòng")
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))

    assert [(row["slug"], row["distance_km"], row["duration_min"]) for row in payload["projects"]] == [
        ("geo-2", 5.0, 10),
        ("geo-1", 30.0, 60),
    ]
    assert calls and calls[0][0] == _ORIGIN
    assert calls[0][1] == [(20.90, 106.70), (21.20, 107.20)]


@pytest.mark.asyncio
async def test_list_active_projects_all_none_estimates_keep_straight_line(no_cache_io):
    """A provider that answers nothing changes nothing — no duration, same km."""
    projects = [_geo_project(1, lat=20.90, lng=106.70), _geo_project(2, lat=21.20, lng=107.20)]
    repo = _make_repo(
        list_active_projects=lambda self: _const(projects),
        geocode_area=_geo_area(),
        estimate_distances_km=_estimates_factory(lambda _o, _d: [None, None]),
    )

    out = await list_active_projects(retrieval=repo, location="Hải Phòng")
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))

    rows = payload["projects"]
    assert [row["distance_km"] for row in rows] == [rows[0]["distance_km"], rows[1]["distance_km"]]
    assert all(row["distance_km"] > 0 for row in rows)
    assert all("duration_min" not in row for row in rows)
    # Straight-line order stands: project 1 (near) before project 2 (far).
    assert rows[0]["slug"] == "geo-1"


@pytest.mark.asyncio
async def test_get_project_distance_reports_road_estimate_with_duration(no_cache_io):
    """The dedicated distance tool quotes the estimate, nearest road first."""
    plants = [
        _geo_project(1, lat=20.90, lng=106.70),   # nearer by straight-line
        _geo_project(2, lat=21.20, lng=107.20),
    ]
    calls: list = []
    repo = _make_repo(
        list_active_projects=lambda self: _const(plants),
        geocode_area=_geo_area(),
        estimate_distances_km=_estimates_factory(
            lambda _origin, _dests: [(42.0, 3900.0), (8.0, 700.0)], calls=calls
        ),
    )

    out = await get_project_distance(retrieval=repo, location="312 Nguyễn Công Hòa", company="AmTRAN")
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))

    assert payload["status"] == "measured"
    assert [(row["project"], row["distance_km"], row["duration_min"]) for row in payload["projects"]] == [
        ("Geo 2", 8.0, 12),
        ("Geo 1", 42.0, 65),
    ]
    assert calls[0][1] == [(20.90, 106.70), (21.20, 107.20)]


@pytest.mark.asyncio
async def test_get_project_distance_without_estimate_method_falls_back(no_cache_io):
    """A port predating estimates (unit fakes) behaves exactly as before."""
    plants = [
        _geo_project(1, lat=20.90, lng=106.70),
        _geo_project(2, lat=21.20, lng=107.20),
    ]
    repo = _make_repo(  # no estimate_distances_km at all
        list_active_projects=lambda self: _const(plants),
        geocode_area=_geo_area(),
    )

    out = await get_project_distance(retrieval=repo, location="312 Nguyễn Công Hòa", company="AmTRAN")
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))

    assert payload["status"] == "measured"
    assert [row["project"] for row in payload["projects"]] == ["Geo 1", "Geo 2"]
    assert all(row["distance_km"] > 0 for row in payload["projects"])
    assert all("duration_min" not in row for row in payload["projects"])


@pytest.mark.asyncio
async def test_get_project_distance_unmatched_name_still_answers_nearest_first(no_cache_io):
    """"AmTRAN bao xa" matches no catalog row (the row is just "AMTRAN", and
    "bao xa" is colloquial). Dead-ending there would throw away an answer the
    data already supports, so the tool falls back to the full nearest-first
    ranking under a status that says the name did not match."""
    plants = [
        _geo_project(1, lat=20.90, lng=106.70),
        _geo_project(2, lat=21.20, lng=107.20),
    ]
    repo = _make_repo(
        list_active_projects=lambda self: _const(plants),
        geocode_area=_geo_area(),
    )

    out = await get_project_distance(
        retrieval=repo, location="312 Nguyễn Công Hòa", company="AmTRAN bao xa"
    )
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))

    assert payload["status"] == "company_unmatched"
    assert [row["project"] for row in payload["projects"]] == ["Geo 1", "Geo 2"]
    assert "không khớp với danh mục" in payload["safe_reply"]


@pytest.mark.asyncio
async def test_get_project_distance_unresolvable_location_asks_for_a_better_address(
    no_cache_io,
):
    """An unresolvable origin is an honest miss, never a guessed distance."""
    repo = _make_repo(
        list_active_projects=lambda self: _const([_geo_project(1, lat=20.90, lng=106.70)]),
        geocode_area=lambda self, q: _none(),
    )

    out = await get_project_distance(retrieval=repo, location="qqq zzz")
    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))

    assert payload["status"] == "unresolved_location"
    assert payload["projects"] == []
    assert "địa chỉ" in payload["safe_reply"]


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
async def test_inactive_project_features_are_not_served_from_a_warm_cache(monkeypatch):
    calls = []

    async def resolve(_repo, slug, **kwargs):
        calls.append((slug, kwargs))
        return None

    cached = AsyncMock(return_value="cached facts about inactive project")
    monkeypatch.setattr("app.graph.tools.catalog.cache_get_json", cached)
    repo = _make_repo(project_id_by_slug=resolve)

    out = await get_product_features(retrieval=repo, project_slug="inactive")

    assert calls == [("inactive", {"active_only": True})]
    assert "Không tìm thấy" in out
    cached.assert_not_awaited()


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

    state = {"exact": None}

    async def _fake_get(key):
        return state["exact"]

    async def _noop_set(*a, **k):
        return None

    async def _noop_version(*a, **k):
        return "0"

    _patch_tool_io(monkeypatch, _S, get=_fake_get, set=_noop_set, version=_noop_version)
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


# ---------------------------------------------------------------------------
# search_knowledge — bounded rendered evidence (tool-result size cap)
# ---------------------------------------------------------------------------


def _knowledge_row(index: int, *, body_len: int):
    """A retrieval row shaped like the repository port returns."""
    return SimpleNamespace(
        id=f"row-{index}",
        metadata={"citation": {"label": f"Nguồn {index}"}},
        source_file=f"docs/{index}.md",
        line_start=None,
        line_end=None,
        source_quote="x" * body_len,
        summary=None,
        content="",
    )


@pytest.mark.asyncio
async def test_search_knowledge_caps_rendered_rows_and_keeps_top(no_cache_io):
    """A large result set is trimmed to the cap and keeps the best-ranked rows."""
    from app.graph.tools import knowledge as knowledge_mod

    cap = knowledge_mod._MAX_EVIDENCE_ROWS
    rows = [_knowledge_row(i, body_len=120) for i in range(cap + 5)]
    repo = _make_repo(
        match_faq=lambda self, emb, *, top_k, project_ids: _const([]),
        match_documents=lambda self, emb, top_k, *_a, **_k: _const(rows),
    )

    out = await search_knowledge(retrieval=repo, embedder=_FakeEmbedder(), query="lương")

    rendered = [line for line in out.splitlines() if line.startswith("- ")]
    assert len(rendered) == cap
    # Best-ranked rows survive; the tail is dropped.
    assert "x" * 120 in rendered[0]
    assert "Nguồn 0" in out
    assert f"Nguồn {cap - 1}" in out
    assert f"Nguồn {cap}" not in out
    # Citation/source suffix format is preserved verbatim.
    assert "Nguồn: Nguồn 0" in out
    assert "file: docs/0.md" in out


@pytest.mark.asyncio
async def test_search_knowledge_caps_total_evidence_characters(no_cache_io):
    """The total rendered-character budget bounds evidence before the row cap."""
    from app.graph.tools import knowledge as knowledge_mod

    # Long rows: the character budget binds before the row cap does. Each row
    # renders to roughly 1339 chars, so the expected count is derived from the
    # configured budget rather than hard-coded.
    cap = knowledge_mod._MAX_EVIDENCE_ROWS
    rows = [_knowledge_row(i, body_len=1300) for i in range(cap)]
    repo = _make_repo(
        match_faq=lambda self, emb, *, top_k, project_ids: _const([]),
        match_documents=lambda self, emb, top_k, *_a, **_k: _const(rows),
    )

    out = await search_knowledge(retrieval=repo, embedder=_FakeEmbedder(), query="lương")

    rendered = [line for line in out.splitlines() if line.startswith("- ")]
    # The character budget binds before the row cap, and what survives is a
    # contiguous best-first prefix: the last rendered row is exactly the next
    # index after the ones kept, with no gaps or skipped rankings.
    assert 0 < len(rendered) < cap
    assert len(out) <= knowledge_mod._MAX_EVIDENCE_CHARS
    assert f"Nguồn {len(rendered) - 1}" in out
    assert f"Nguồn {len(rendered)}" not in out


@pytest.mark.asyncio
async def test_search_knowledge_truncates_a_single_oversized_row(no_cache_io):
    """One row larger than the whole budget is clipped, not dropped."""
    from app.graph.tools import knowledge as knowledge_mod

    rows = [_knowledge_row(0, body_len=knowledge_mod._MAX_EVIDENCE_CHARS * 2)]
    repo = _make_repo(
        match_faq=lambda self, emb, *, top_k, project_ids: _const([]),
        match_documents=lambda self, emb, top_k, *_a, **_k: _const(rows),
    )

    out = await search_knowledge(retrieval=repo, embedder=_FakeEmbedder(), query="lương")

    assert len(out) <= knowledge_mod._MAX_EVIDENCE_CHARS
    assert "Nguồn 0" in out
    assert "file: docs/0.md" in out  # suffix survives the clip


# ---------------------------------------------------------------------------
# search_knowledge — cache-key determinism (project-id order must not matter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_knowledge_cache_key_ignores_project_id_order(
    monkeypatch, cache_enabled_io
):
    """The project-id list feeds the cache digest, so DB row order must not
    change the key: two fetches of the same ids in different orders must
    produce one identical key."""
    seen: list[str] = []

    async def _recording_get(key):
        seen.append(key)
        return "HIT"

    monkeypatch.setattr("app.graph.tools.knowledge.cache_get_json", _recording_get)

    repo_a = _make_repo(active_project_ids=lambda self: _const(["p2", "p1"]))
    repo_b = _make_repo(active_project_ids=lambda self: _const(["p1", "p2"]))
    out_a = await search_knowledge(retrieval=repo_a, embedder=_FakeEmbedder(), query="luong")
    out_b = await search_knowledge(retrieval=repo_b, embedder=_FakeEmbedder(), query="luong")

    assert out_a == out_b == "HIT"
    assert len(seen) == 2
    assert seen[0] == seen[1]


# ---------------------------------------------------------------------------
# search_knowledge — single-flight gate is the config flag only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_knowledge_singleflight_engages_for_scoped_lookups(
    monkeypatch, no_cache_io
):
    """The single-flight key IS the full cache key (query + project scope +
    knowledge version), so a project-scoped lookup must be eligible for
    coalescing when the flag is on."""
    calls: list = []

    async def _coalesced(**kwargs):
        calls.append(kwargs)
        return "COALESCED"

    monkeypatch.setattr("app.graph.tools.knowledge._search_knowledge_coalesced", _coalesced)
    s = SimpleNamespace(rag_cache_enabled=False, singleflight_enabled=True)
    monkeypatch.setattr("app.graph.tools.knowledge.get_settings", lambda: s)

    repo = _make_repo(active_project_ids=lambda self: _const(["p1"]))
    out = await search_knowledge(retrieval=repo, embedder=_FakeEmbedder(), query="luong")

    assert out == "COALESCED"
    assert len(calls) == 1
    assert calls[0]["cache_key"].startswith("rag:knowledge:")


@pytest.mark.asyncio
async def test_search_knowledge_singleflight_engages_for_unscoped_lookups(
    monkeypatch, no_cache_io
):
    """No project scope at all must stay eligible for coalescing (the old
    ``project_ids is None`` requirement was a tautology for this arm)."""
    calls: list = []

    async def _coalesced(**kwargs):
        calls.append(kwargs)
        return "COALESCED"

    monkeypatch.setattr("app.graph.tools.knowledge._search_knowledge_coalesced", _coalesced)
    s = SimpleNamespace(rag_cache_enabled=False, singleflight_enabled=True)
    monkeypatch.setattr("app.graph.tools.knowledge.get_settings", lambda: s)

    repo = _make_repo()  # no active_project_ids attr → project_ids None
    out = await search_knowledge(retrieval=repo, embedder=_FakeEmbedder(), query="luong")

    assert out == "COALESCED"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_search_knowledge_singleflight_disabled_by_default(monkeypatch, no_cache_io):
    """Without the flag the coalescing wrapper is never invoked and the
    direct compute path answers."""
    calls: list = []

    async def _coalesced(**kwargs):
        calls.append(kwargs)
        return "COALESCED"

    monkeypatch.setattr("app.graph.tools.knowledge._search_knowledge_coalesced", _coalesced)

    repo = _make_repo(
        match_faq=lambda self, emb, *, top_k, project_ids: _const([]),
        match_documents=lambda self, emb, top_k, *_a, **_k: _const([]),
    )
    out = await search_knowledge(retrieval=repo, embedder=_FakeEmbedder(), query="luong")

    assert "Không tìm thấy" in out
    assert calls == []


# ---------------------------------------------------------------------------
# cached_embed / packed float16 wire format — normalised key + packed payload
# ---------------------------------------------------------------------------


class TestCachedEmbed:
    def _settings(self):
        return SimpleNamespace(
            rag_cache_enabled=True,
            embedding_provider="openrouter",
            openrouter_embedding_model="text-embedding-test",
            gemini_embedding_model="gemini-test",
            embedding_dim=8,
            embedding_cache_ttl_seconds=60,
        )

    def test_pack_unpack_roundtrip(self):
        vec = [0.5, -1.25, 3.0, 0.0]
        assert unpack_vector(pack_vector(vec)) == vec

    def test_unpack_rejects_legacy_and_corrupt_payloads(self):
        assert unpack_vector([0.1, 0.2]) is None  # legacy JSON array
        assert unpack_vector("khong-phai-base64 !!") is None
        assert unpack_vector(None) is None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_embedder(self, monkeypatch):
        monkeypatch.setattr(embed_cache, "get_settings", lambda: self._settings())
        packed = pack_vector([0.5, 0.25])

        async def _get(key):
            return packed

        monkeypatch.setattr(embed_cache, "cache_get_json", _get)
        embedder = _FakeEmbedder()

        out = await embed_cache.cached_embed(embedder, "Luong bao nhieu?")

        assert out == [0.5, 0.25]
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_normalised_variants_share_one_key_and_store_packed(self, monkeypatch):
        """Case/whitespace variants hash to one key; the embedder still
        receives the raw query, and the stored value is the packed string."""
        monkeypatch.setattr(embed_cache, "get_settings", lambda: self._settings())
        gets: list[str] = []
        sets: list[tuple] = []

        async def _get(key):
            gets.append(key)
            return None

        async def _set(key, value, ttl):
            sets.append((key, value, ttl))

        monkeypatch.setattr(embed_cache, "cache_get_json", _get)
        monkeypatch.setattr(embed_cache, "cache_set_json", _set)
        embedder = _FakeEmbedder(vec=[0.5] * 8)

        await embed_cache.cached_embed(embedder, "  LƯƠNG BAO NHIÊU ")
        await embed_cache.cached_embed(embedder, "lương bao nhiêu")

        assert gets[0] == gets[1]
        # The embedder is called with the raw queries, not the normalised form.
        assert embedder.calls == ["  LƯƠNG BAO NHIÊU ", "lương bao nhiêu"]
        key, value, ttl = sets[0]
        assert key == gets[0]
        assert isinstance(value, str)
        assert unpack_vector(value) == [0.5] * 8
        assert ttl == 60


# ---------------------------------------------------------------------------
# Geo-distance rows ("dự án nào gần nhà")
# ---------------------------------------------------------------------------

# KCN Tràng Duệ (An Dương) and KCN Nomura (Hồng An) are ~5 km apart; the third
# project has no coordinates, so it must carry no distance and sort last.
_DISTANCE_CATALOG = [
    ProjectFeatures(
        project_id="bbbbbbbb-1111-4111-8111-111111111111",
        slug="kcn-nomura",
        name="Nomura",
        province="Hải Phòng",
        district="Hồng An",
        address="KCN Nhật Bản, Hồng An, Hải Phòng",
        latitude=20.90,
        longitude=106.72,
    ),
    ProjectFeatures(
        project_id="cccccccc-1111-4111-8111-111111111111",
        slug="khong-toa-do",
        name="Không toạ độ",
        province="Hải Phòng",
        district="An Dương",
    ),
    ProjectFeatures(
        project_id="dddddddd-1111-4111-8111-111111111111",
        slug="kcn-trang-due",
        name="Tràng Duệ",
        province="Hải Phòng",
        district="An Dương",
        address="KCN Tràng Duệ, An Dương, Hải Phòng",
        latitude=20.86,
        longitude=106.68,
    ),
]


@pytest.mark.asyncio
async def test_list_active_projects_reports_distance_nearest_first(no_cache_io):
    queried: list[str] = []
    repo = _make_repo(
        list_active_projects=lambda self: _const(_DISTANCE_CATALOG),
        geocode_area=_geo_area(calls=queried),
    )

    out = await list_active_projects(retrieval=repo, location="An Dương")

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    rows = payload["projects"]
    assert [row["slug"] for row in rows] == ["kcn-trang-due", "kcn-nomura", "khong-toa-do"]
    assert rows[0]["distance_km"] == 0.0
    assert 3.0 <= rows[1]["distance_km"] <= 8.0
    assert "distance_km" not in rows[2]
    assert "cách " in " ".join(rows[0]["fit_notes"])
    assert "cách " in " ".join(rows[1]["fit_notes"])
    assert "cách " not in " ".join(rows[2]["fit_notes"])
    assert queried == ["An Dương"]


@pytest.mark.asyncio
async def test_list_active_projects_without_geocoded_origin_keeps_the_previous_output(
    no_cache_io,
):
    """A geocoder miss must reproduce the pre-change order, notes, and payload."""
    repo = _make_repo(
        list_active_projects=lambda self: _const(_DISTANCE_CATALOG),
        geocode_area=_geo_area(None),
    )

    out = await list_active_projects(retrieval=repo, location="An Dương")

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    rows = payload["projects"]
    assert [row["slug"] for row in rows] == ["khong-toa-do", "kcn-trang-due", "kcn-nomura"]
    assert all("distance_km" not in row for row in rows)
    assert all("cách " not in note for row in rows for note in row["fit_notes"])


@pytest.mark.asyncio
async def test_list_active_projects_without_location_never_geocodes(no_cache_io):
    queried: list[str] = []
    repo = _make_repo(
        list_active_projects=lambda self: _const(_DISTANCE_CATALOG),
        geocode_area=_geo_area(calls=queried),
    )

    out = await list_active_projects(retrieval=repo, company="nomura")

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_PROJECT_LOOKUP_JSON="))
    assert queried == []
    assert all("distance_km" not in row for row in payload["projects"])
