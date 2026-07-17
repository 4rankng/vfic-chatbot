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
