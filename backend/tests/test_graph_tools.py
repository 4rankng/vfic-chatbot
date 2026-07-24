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
        "compare_income",
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

    payload = json.loads(out.splitlines()[0].removeprefix("COMPARE_INCOME_JSON="))
    assert payload["status"] == "matched"
    assert payload["target_monthly_vnd"] == 20_000_000
    assert payload["projects"][0]["project_slug"] == "rorze"
    assert "comparison" not in payload["projects"][0]
    assert "comparison" not in payload["projects"][1]
    assert "14-15 triệu/tháng" in out
    assert "20-21 triệu/tháng" in out
    assert "Kỳ lương" in out
    assert [item["feature_key"] for item in payload["projects"][0]["evidence"]] == [
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

    payload = json.loads(out.splitlines()[0].removeprefix("COMPARE_INCOME_JSON="))
    assert len(payload["projects"]) == 20
    assert payload["projects"][0]["project_slug"] == "rorze"


@pytest.mark.asyncio
async def test_compare_income_reports_retrieval_failure_as_unavailable(no_cache_io):
    async def fail(self):
        raise RuntimeError("database unavailable")

    out = await compare_income(
        retrieval=_make_repo(income_summary_for_active_projects=fail),
        target_monthly_vnd=20_000_000,
    )

    payload = json.loads(out.splitlines()[0].removeprefix("COMPARE_INCOME_JSON="))
    assert payload["status"] == "unavailable"
    assert payload["projects"] == []
    assert "chưa thể kiểm tra dữ liệu thu nhập" in payload["safe_reply"]
    assert "chưa có dữ liệu thu nhập" not in payload["safe_reply"]


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
    assert (
        "LG Display; Tràng Duệ; Hải Phòng; lương 10-14 triệu"
        in payload["safe_reply"]
    )
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
    assert payload["safe_reply"] == (
        "VFIC hiện có các vị trí đang tuyển sau:\n"
        "- Nhân viên lắp ráp / Nhân viên vận hành máy CNC: "
        "Rorze; KCN Nhật Bản (Nomura), Hồng An, Hải Phòng\n"
        "Bạn muốn tìm hiểu vị trí nào ạ?"
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
    # Candidate-facing pivot: the alternative title appears in the trusted text.
    assert "Công nhân sản xuất" in payload["safe_reply"]
    assert "Hiện chưa có vị trí đang tuyển phù hợp" in payload["safe_reply"]
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
