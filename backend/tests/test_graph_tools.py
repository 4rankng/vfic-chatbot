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

import pytest

from app.graph import tools
from app.graph.grounding import extract_surfaced_job_ids
from app.recruitment.domain.recommendation import ActiveProjectIncomeSummary, IncomeFeatureEvidence
from app.graph.tools import (
    TOOLS_REGISTRY,
    _format_knowledge_row,
    compare_income,
    get_product_features,
    list_active_jobs,
    list_active_projects,
    recommend_projects,
    search_bus_timetable,
    search_knowledge,
    search_user_memory,
)
from app.graph.income_contract import IncomeVerdict
from app.graph.tools.jobs import _PRESENTATION_CONTRACT

# The tools package splits tool logic into domain modules; each holds its own
# module-level binding of get_settings/cache helpers, so the cache fixtures
# below patch every submodule (not just the package attribute).
_TOOL_MODULES = tuple(
    getattr(tools, name)
    for name in ("_shared", "memory", "knowledge", "jobs", "income", "catalog")
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
        "list_active_jobs",
        "list_active_projects",
        "recommend_projects",
        "recommend_jobs",
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

    # The original scoped lookup is always sent with explicit filters bounded to top_k.
    assert calls[0] == {
        "project_slug": None,
        "role": "thợ hàn",
        "company": "LG",
        "location": "Hải Phòng",
        "top_k": 10,
        "sort_by": None,
    }
    # No-match now triggers a second unscoped lookup so the LLM can pivot to
    # concrete alternatives instead of asking a round-trip yes/no question.
    assert calls[1] == {
        "project_slug": None,
        "role": None,
        "company": None,
        "location": None,
        "top_k": 10,
    }
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
    assert payload["jobs"][0]["title_plain"] == "Công nhân sản xuất"
    assert payload["safe_reply"] == _PRESENTATION_CONTRACT
    assert "description" not in payload["jobs"][0]
    assert "requirements" not in payload["jobs"][0]
    assert "benefits" not in payload["jobs"][0]
    assert untrusted_id not in out
    assert "SECURITY_BOUNDARY" in out
    assert extract_surfaced_job_ids([out]) == {job_id}


@pytest.mark.asyncio
async def test_list_active_jobs_renders_vietnamese_status_without_duplicate_company_factory(
    no_cache_io,
):
    jobs = (
        SimpleNamespace(
            id="f7daba3b-9882-49d9-97c5-893b34b16995",
            title="Nhân viên lắp ráp / Nhân viên vận hành máy CNC",
            company_name="Rorze",
            factory_name="Rorze",
            project_name="Rorze",
            project_slug="rorze",
            province="KCN Nhật Bản (Nomura), Hồng An, Hải Phòng",
            district=None,
            salary_min=None,
            salary_max=None,
            vacancy_count=None,
        ),
    )
    repo = _make_repo(
        list_active_jobs=lambda self, **kwargs: _const(
            SimpleNamespace(status="matched", jobs=jobs)
        )
    )

    out = await list_active_jobs(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["safe_reply"] == _PRESENTATION_CONTRACT
    # "vận hành máy CNC" already names the machine — title stays unglossed.
    assert payload["jobs"][0]["title_plain"] == (
        "Nhân viên lắp ráp / Nhân viên vận hành máy CNC"
    )
    assert payload["jobs"][0]["company"] == "Rorze"


@pytest.mark.asyncio
async def test_list_active_jobs_groups_large_catalogs_and_glosses_jargon(no_cache_io):
    """The operator persona forbids dumping 5-10 rows on a phone screen.

    With more than four matched jobs the safe reply collapses into one block
    per company (distinct locations + salary summaries in the header, plain
    -language titles inside), and internal abbreviations (SMT, QA) are glossed
    so the candidate never reads bare internal codes.
    """
    jobs = (
        SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            title="SMT",
            company_name="4P Electronics",
            factory_name="4P",
            project_name="4P Electronics",
            project_slug="4p-electronics",
            province="Hải Phòng",
            district=None,
            salary_min=6_300_000,
            salary_max=16_000_000,
            vacancy_count=None,
        ),
        SimpleNamespace(
            id="22222222-2222-4222-8222-222222222222",
            title="PCBA",
            company_name="4P Electronics",
            factory_name="4P",
            project_name="4P Electronics",
            project_slug="4p-electronics",
            province="Hải Phòng",
            district=None,
            salary_min=6_300_000,
            salary_max=16_000_000,
            vacancy_count=None,
        ),
        SimpleNamespace(
            id="33333333-3333-4333-8333-333333333333",
            title="Chất lượng QA",
            company_name="4P Electronics",
            factory_name="4P",
            project_name="4P Electronics",
            project_slug="4p-electronics",
            province="Hải Phòng",
            district=None,
            salary_min=6_300_000,
            salary_max=16_000_000,
            vacancy_count=None,
        ),
        SimpleNamespace(
            id="44444444-4444-4444-8444-444444444444",
            title="QA",
            company_name="AMTRAN",
            factory_name="AMTRAN",
            project_name="AMTRAN",
            project_slug="amtran",
            province="Hải Phòng",
            district=None,
            salary_min=6_300_000,
            salary_max=None,
            vacancy_count=None,
        ),
        SimpleNamespace(
            id="55555555-5555-4555-8555-555555555555",
            title="Nhân viên vận hành máy CNC",
            company_name="Rorze",
            factory_name="Rorze",
            project_name="Rorze",
            project_slug="rorze",
            province="KCN Nhật Bản (Nomura), Hồng An, Hải Phòng",
            district=None,
            salary_min=14_000_000,
            salary_max=15_000_000,
            vacancy_count=None,
        ),
    )
    repo = _make_repo(
        list_active_jobs=lambda self, **kwargs: _const(
            SimpleNamespace(status="matched", jobs=jobs)
        )
    )

    out = await list_active_jobs(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    # Evidence-only contract: the payload is data (title_plain de-jargoned) and
    # the grouping rule is a presentation instruction — the LLM agent composes
    # the final reply, so there is no canned candidate-facing text.
    assert payload["safe_reply"] == _PRESENTATION_CONTRACT
    assert "nhóm theo dự án/công ty" in _PRESENTATION_CONTRACT
    assert payload["jobs"][0]["title_plain"] == (
        "SMT (gắn linh kiện điện tử bằng máy tự động)"
    )
    assert payload["jobs"][1]["title_plain"] == "PCBA (lắp ráp bo mạch điện tử)"
    # "Chất lượng QA" already says it — no double gloss; bare "QA" gets one.
    assert payload["jobs"][2]["title_plain"] == "Chất lượng QA"
    assert payload["jobs"][3]["title_plain"] == "QA (kiểm tra chất lượng sản phẩm)"
    # "vận hành máy CNC" already says it — no gloss.
    assert payload["jobs"][4]["title_plain"] == "Nhân viên vận hành máy CNC"
    # The structured payload keeps every row for grounding.
    assert len(payload["jobs"]) == 5


@pytest.mark.asyncio
async def test_list_active_jobs_small_catalog_keeps_per_job_lines_with_glosses(no_cache_io):
    """Small catalogs keep the one-line-per-job shape, titles glossed."""
    jobs = (
        SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            title="SMT",
            company_name="4P Electronics",
            factory_name="4P",
            project_name="4P Electronics",
            project_slug="4p-electronics",
            province="Hải Phòng",
            district=None,
            salary_min=6_300_000,
            salary_max=None,
            vacancy_count=None,
        ),
        SimpleNamespace(
            id="22222222-2222-4222-8222-222222222222",
            title="Nhân viên lắp ráp / Nhân viên vận hành máy CNC",
            company_name="Rorze",
            factory_name="Rorze",
            project_name="Rorze",
            project_slug="rorze",
            province="KCN Nhật Bản (Nomura), Hồng An, Hải Phòng",
            district=None,
            salary_min=None,
            salary_max=None,
            vacancy_count=None,
        ),
    )
    repo = _make_repo(
        list_active_jobs=lambda self, **kwargs: _const(
            SimpleNamespace(status="matched", jobs=jobs)
        )
    )

    out = await list_active_jobs(retrieval=repo)

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["safe_reply"] == _PRESENTATION_CONTRACT
    assert payload["jobs"][0]["title_plain"] == (
        "SMT (gắn linh kiện điện tử bằng máy tự động)"
    )
    # "vận hành máy CNC" already says it — no gloss.
    assert payload["jobs"][1]["title_plain"] == (
        "Nhân viên lắp ráp / Nhân viên vận hành máy CNC"
    )


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


@pytest.mark.asyncio
async def test_list_active_jobs_no_match_surfaces_alternatives_in_safe_reply(no_cache_io):
    """A no-match must pivot the candidate toward concrete open positions.

    The structured ``jobs`` array stays empty (the validator contract that lets
    the authority layer trust the abstention status), but ``safe_reply`` now
    embeds the alternative titles so the LLM can steer the candidate in the
    same turn instead of asking a round-trip yes/no question.
    """
    alt_job = SimpleNamespace(
        id="33333333-3333-4333-8333-333333333333",
        title="Công nhân sản xuất",
        company_name="LG Display",
        factory_name="Tràng Duệ",
        project_name="LG Display Hải Phòng",
        project_slug="lg-display",
        province="Hải Phòng",
        district="",
        address="",
        salary_min=10_000_000,
        salary_max=14_000_000,
        vacancy_count=20,
    )

    async def _list(self, **kwargs):
        if kwargs.get("role"):
            return SimpleNamespace(status="no_match", jobs=())
        return SimpleNamespace(status="matched", jobs=(alt_job,))

    out = await list_active_jobs(
        retrieval=_make_repo(list_active_jobs=_list),
        role="nhân viên lắp ráp",
    )

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["status"] == "no_match"
    # Validator contract: a non-matched status must keep jobs empty.
    assert payload["jobs"] == []
    # Candidate-facing pivot: alternatives are structured rows with de-jargoned
    # titles, and the safe_reply slot frames them as evidence for the agent.
    assert payload["alternative_jobs"][0]["title_plain"] == "Công nhân sản xuất"
    assert "Hiện chưa có vị trí đang tuyển phù hợp" in payload["safe_reply"]
    assert "alternative_jobs" in payload["safe_reply"]
    # Alternatives are structured grounding evidence even though ``jobs`` stays
    # empty, so their IDs and entities can be validated without changing the
    # trusted no-match status.
    assert payload["alternative_jobs"][0]["id"] == alt_job.id
    assert payload["alternative_jobs"][0]["company"] == "LG Display"
    assert f"SURFACED_JOB_IDS=id={alt_job.id}" in out


@pytest.mark.asyncio
async def test_list_active_jobs_no_match_without_alternatives_stays_honest(no_cache_io):
    """If no alternative positions exist either, the reply must not fabricate any.

    Guards against the alternatives lookup accidentally surfacing stale or
    empty rows as if they were real openings.
    """

    async def _list(self, **kwargs):
        if kwargs.get("role"):
            return SimpleNamespace(status="no_match", jobs=())
        return SimpleNamespace(status="catalog_empty", jobs=())

    out = await list_active_jobs(
        retrieval=_make_repo(list_active_jobs=_list),
        role="nhân viên lắp ráp",
    )

    payload = json.loads(out.splitlines()[0].removeprefix("ACTIVE_JOB_LOOKUP_JSON="))
    assert payload["status"] == "no_match"
    assert payload["jobs"] == []
    assert "Hiện chưa có vị trí đang tuyển phù hợp" in payload["safe_reply"]
    # No fake alternative title leaks in.
    assert "đang tuyển các vị trí" not in payload["safe_reply"]


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
async def test_recommend_projects_default_shortlist_covers_five_scored_rows(no_cache_io):
    """Omitting top_k must not hide scored candidates behind the old default of 3.

    The model does the relevance filtering, so the default shortlist is 5 —
    with six scored projects, exactly the cap's worth are rendered, ranked.
    """
    rows = [
        SimpleNamespace(
            slug=f"project-{index}",
            name=f"Project {index}",
            summary="Tuyển nhân viên kho tại Hải Phòng",
            index_card={"key_roles": ["nhân viên kho"], "location": "Hải Phòng"},
        )
        for index in range(1, 7)
    ]
    repo = _make_repo(active_projects_with_card=lambda self: _const(rows))

    out = await recommend_projects(retrieval=repo, query="việc kho tại Hải Phòng")

    rendered = [line for line in out.splitlines() if line.startswith("- ")]
    assert len(rendered) == 5
    assert rendered[0].startswith("- project-1")


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

    assert out == "Hiện chưa có việc làm đang tuyển phù hợp với hồ sơ này."


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
# _cached_embed — normalised key + packed float16 payload
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
        shared = tools._shared
        vec = [0.5, -1.25, 3.0, 0.0]
        assert shared._unpack_vector(shared._pack_vector(vec)) == vec

    def test_unpack_rejects_legacy_and_corrupt_payloads(self):
        shared = tools._shared
        assert shared._unpack_vector([0.1, 0.2]) is None  # legacy JSON array
        assert shared._unpack_vector("khong-phai-base64 !!") is None
        assert shared._unpack_vector(None) is None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_embedder(self, monkeypatch):
        monkeypatch.setattr(tools._shared, "get_settings", lambda: self._settings())
        packed = tools._shared._pack_vector([0.5, 0.25])

        async def _get(key):
            return packed

        monkeypatch.setattr(tools._shared, "cache_get_json", _get)
        embedder = _FakeEmbedder()

        out = await tools._shared._cached_embed(embedder, "Luong bao nhieu?")

        assert out == [0.5, 0.25]
        assert embedder.calls == []

    @pytest.mark.asyncio
    async def test_normalised_variants_share_one_key_and_store_packed(self, monkeypatch):
        """Case/whitespace variants hash to one key; the embedder still
        receives the raw query, and the stored value is the packed string."""
        monkeypatch.setattr(tools._shared, "get_settings", lambda: self._settings())
        gets: list[str] = []
        sets: list[tuple] = []

        async def _get(key):
            gets.append(key)
            return None

        async def _set(key, value, ttl):
            sets.append((key, value, ttl))

        monkeypatch.setattr(tools._shared, "cache_get_json", _get)
        monkeypatch.setattr(tools._shared, "cache_set_json", _set)
        embedder = _FakeEmbedder(vec=[0.5] * 8)

        await tools._shared._cached_embed(embedder, "  LƯƠNG BAO NHIÊU ")
        await tools._shared._cached_embed(embedder, "lương bao nhiêu")

        assert gets[0] == gets[1]
        # The embedder is called with the raw queries, not the normalised form.
        assert embedder.calls == ["  LƯƠNG BAO NHIÊU ", "lương bao nhiêu"]
        key, value, ttl = sets[0]
        assert key == gets[0]
        assert isinstance(value, str)
        assert tools._shared._unpack_vector(value) == [0.5] * 8
        assert ttl == 60
