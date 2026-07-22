"""Pure contract tests for explicit ACTIVE-job semantic filtering."""

from __future__ import annotations

from app.services.recommendation.availability import ActiveJob, select_matching_active_jobs


def _job(**overrides) -> ActiveJob:
    values = {
        "id": "job-1",
        "title": "Thợ hàn CO2",
        "company_name": "VFIC Manufacturing",
        "factory_name": "Nhà máy A",
        "province": "Hải Phòng",
        "district": "An Dương",
        "address": "Khu công nghiệp Tràng Duệ",
        "salary_min": 10_000_000,
        "salary_max": 14_000_000,
        "vacancy_count": 1,
    }
    values.update(overrides)
    return ActiveJob(**values)


def test_omitted_filters_list_the_scoped_catalog_in_input_order():
    jobs = [_job(), _job(id="job-2", title="Nhân viên kho")]

    outcome = select_matching_active_jobs(jobs)

    assert outcome.status == "matched"
    assert outcome.jobs == tuple(jobs)


def test_role_filter_matches_only_the_structured_title():
    welder = _job()
    operator = _job(id="job-2", title="Công nhân sản xuất", description="Hỗ trợ thợ hàn")

    outcome = select_matching_active_jobs([operator, welder], role="thợ hàn CO2")

    assert outcome.status == "matched"
    assert outcome.jobs == (welder,)


def test_company_filter_matches_short_alias_and_project_identity():
    lg_job = _job(
        company_name="Công ty TNHH Điện tử",
        company_aliases=("LG", "LGD"),
        project_name="LG Display Tràng Duệ",
        project_slug="lg-display",
    )
    other = _job(id="job-2", company_name="Samsung Display")

    alias_match = select_matching_active_jobs([other, lg_job], company="LG")
    project_match = select_matching_active_jobs([other, lg_job], company="LG Display")

    assert alias_match.jobs == (lg_job,)
    assert project_match.jobs == (lg_job,)


def test_identity_filter_tolerates_a_long_company_typo():
    lg_job = _job(company_name="LG Display")

    outcome = select_matching_active_jobs([lg_job], company="LG Dislay")

    assert outcome.status == "matched"
    assert outcome.jobs == (lg_job,)


def test_location_filter_matches_province_district_or_address():
    hai_phong = _job()
    bac_ninh = _job(
        id="job-2",
        province="Bắc Ninh",
        district="Yên Phong",
        address="Khu công nghiệp Yên Phong",
    )

    assert select_matching_active_jobs([bac_ninh, hai_phong], location="Hải Phòng").jobs == (
        hai_phong,
    )
    assert select_matching_active_jobs([hai_phong, bac_ninh], location="Yên Phong").jobs == (
        bac_ninh,
    )


def test_company_match_does_not_authorize_an_absent_role():
    lg_operator = _job(title="Công nhân sản xuất", company_name="LG Display")

    outcome = select_matching_active_jobs(
        [lg_operator],
        role="thợ hàn",
        company="LG",
    )

    assert outcome.status == "no_match"
    assert outcome.jobs == ()


def test_filter_values_are_not_processed_as_conversational_queries():
    job = _job(company_name="LG Display")

    outcome = select_matching_active_jobs([job], company="LG đang tuyển ạ")

    assert outcome.status == "no_match"


def test_role_matching_uses_whole_tokens_without_identity_typo_fuzzing():
    unrelated = _job(title="Nhân viên thông tin")

    substring = select_matching_active_jobs([unrelated], role="thợ")
    typo = select_matching_active_jobs([_job()], role="thợ hàm")

    assert substring.status == "no_match"
    assert typo.status == "no_match"


def test_empty_structured_catalog_is_distinct_from_no_match():
    outcome = select_matching_active_jobs([], role="thợ hàn")

    assert outcome.status == "catalog_empty"
    assert outcome.jobs == ()


def test_top_k_is_bounded_and_never_returns_zero_for_a_match():
    jobs = [_job(id=f"job-{index}") for index in range(12)]

    assert len(select_matching_active_jobs(jobs, top_k=100).jobs) == 10
    assert select_matching_active_jobs(jobs, top_k=0).jobs == (jobs[0],)


# --- Salary-based sorting ----------------------------------------------------
#
# Candidates ask "sắp xếp theo lương từ cao xuống thấp". ``sort_by`` reorders
# matches by salary magnitude so the LLM receives a salary-ranked list instead
# of the default recency order. Jobs without salary always sink to the bottom
# so they remain visible rather than being dropped by a bounded top_k.


def test_sort_by_salary_desc_ranks_highest_ceiling_first():
    low = _job(id="low", salary_min=7_000_000, salary_max=7_000_000, title="Công nhân A")
    mid = _job(id="mid", salary_min=10_000_000, salary_max=12_000_000, title="Công nhân B")
    high = _job(id="high", salary_min=12_000_000, salary_max=15_000_000, title="Công nhân C")

    outcome = select_matching_active_jobs([low, high, mid], sort_by="salary_desc")

    assert outcome.status == "matched"
    assert [job.id for job in outcome.jobs] == ["high", "mid", "low"]


def test_sort_by_salary_asc_ranks_lowest_first():
    low = _job(id="low", salary_min=7_000_000, salary_max=7_000_000, title="Công nhân A")
    mid = _job(id="mid", salary_min=10_000_000, salary_max=12_000_000, title="Công nhân B")
    high = _job(id="high", salary_min=12_000_000, salary_max=15_000_000, title="Công nhân C")

    outcome = select_matching_active_jobs([high, low, mid], sort_by="salary_asc")

    assert [job.id for job in outcome.jobs] == ["low", "mid", "high"]


def test_sort_by_salary_desc_falls_back_to_salary_min_when_max_missing():
    # A job with only salary_min should still sort by that figure, not by zero.
    floor_only = _job(
        id="floor", salary_min=13_000_000, salary_max=None, title="Công nhân D"
    )
    lower = _job(id="lower", salary_min=7_000_000, salary_max=9_000_000, title="Công nhân E")

    outcome = select_matching_active_jobs([lower, floor_only], sort_by="salary_desc")

    assert [job.id for job in outcome.jobs] == ["floor", "lower"]


def test_sort_by_salary_desc_puts_unsalaried_jobs_last():
    salaried = _job(id="salaried", salary_min=7_000_000, salary_max=7_000_000, title="Công nhân A")
    unsalaried = _job(id="unknown", salary_min=None, salary_max=None, title="Công nhân B")

    outcome = select_matching_active_jobs([unsalaried, salaried], sort_by="salary_desc")

    assert [job.id for job in outcome.jobs] == ["salaried", "unknown"]


def test_sort_by_salary_asc_also_puts_unsalaried_jobs_last():
    salaried = _job(id="salaried", salary_min=7_000_000, salary_max=7_000_000, title="A")
    unsalaried = _job(id="unknown", salary_min=None, salary_max=None, title="B")

    outcome = select_matching_active_jobs([unsalaried, salaried], sort_by="salary_asc")

    assert [job.id for job in outcome.jobs] == ["salaried", "unknown"]


def test_sort_by_salary_desc_with_top_k_keeps_highest_paid():
    jobs = [
        _job(id=f"job-{i}", salary_max=i * 1_000_000, title=f"Vị trí {i}")
        for i in range(1, 6)  # salary_max 1M..5M
    ]

    outcome = select_matching_active_jobs(jobs, sort_by="salary_desc", top_k=2)

    assert [job.id for job in outcome.jobs] == ["job-5", "job-4"]


def test_sort_by_omitted_preserves_input_order():
    # Default behavior (no sort_by) must not reorder — regression guard.
    first = _job(id="first", salary_max=15_000_000, title="A")
    second = _job(id="second", salary_max=7_000_000, title="B")

    outcome = select_matching_active_jobs([first, second])

    assert [job.id for job in outcome.jobs] == ["first", "second"]
