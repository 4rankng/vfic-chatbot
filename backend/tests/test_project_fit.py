"""Pure project-fit ranking tests for the project-first matching authority.

The matching unit is the project: ``rank_projects`` returns EVERY active
project ordered by fit — never capped, never a "no match" answer — annotated
per stated preference with what the project satisfies vs. differs.
"""

from __future__ import annotations

from datetime import datetime

from app.recruitment.domain.recommendation import (
    ProjectFeatures,
    ProjectScopeItem,
    rank_projects,
)


def _project(
    project_id: str,
    name: str,
    *,
    company: str = "",
    factory: str = "",
    province: str = "",
    district: str = "",
    address: str = "",
    salary_min: int | None = None,
    salary_max: int | None = None,
    scope: tuple[ProjectScopeItem, ...] = (),
    updated_at: datetime | None = None,
) -> ProjectFeatures:
    return ProjectFeatures(
        project_id=project_id,
        slug=project_id,
        name=name,
        company=company,
        factory=factory,
        province=province,
        district=district,
        address=address,
        updated_at=updated_at,
        salary_min=salary_min,
        salary_max=salary_max,
        scope=scope,
    )


_RORZE_LIKE = _project(
    "rorze",
    "Rorze",
    company="Rorze Corporation",
    province="Hải Phòng",
    salary_min=6_300_000,
    salary_max=10_000_000,
    scope=(
        ProjectScopeItem("Nhân viên lắp ráp", 6_300_000, 10_000_000),
        ProjectScopeItem("Nhân viên vận hành máy CNC", 6_300_000, 10_000_000),
    ),
)


def _catalog(count: int = 12) -> list[ProjectFeatures]:
    filler = [
        _project(
            f"proj-{index:02d}",
            f"Dự án {index:02d}",
            province="Bắc Ninh",
            salary_min=5_000_000,
            salary_max=7_000_000,
            scope=(ProjectScopeItem("Công nhân sản xuất", 5_000_000, 7_000_000),),
        )
        for index in range(count - 3)
    ]
    lg_like = _project(
        "lg",
        "LG Display",
        company="LG Display",
        province="Hà Nội",
        salary_min=8_000_000,
        salary_max=12_000_000,
        scope=(ProjectScopeItem("Công nhân sản xuất", 8_000_000, 12_000_000),),
    )
    cnc_project = _project(
        "cnc",
        "AMTRAN CNC",
        company="AMTRAN",
        province="Hải Phòng",
        salary_min=14_000_000,
        salary_max=15_000_000,
        scope=(ProjectScopeItem("Vận hành máy CNC", 14_000_000, 15_000_000),),
    )
    return [_RORZE_LIKE, lg_like, cnc_project, *filler[: count - 3]]


def test_rank_projects_never_caps_the_catalog():
    projects = _catalog(12)
    lookup = rank_projects(projects, job_scope="lắp ráp")
    assert lookup.status == "matched"
    assert len(lookup.fits) == 12
    assert lookup.total == 12


def test_rank_projects_empty_catalog_is_catalog_empty():
    lookup = rank_projects([])
    assert lookup.status == "catalog_empty"
    assert lookup.fits == ()
    assert lookup.total == 0


def test_rank_projects_orders_by_fit_with_honest_dimension_notes():
    lookup = rank_projects(
        _catalog(12),
        job_scope="lắp ráp",
        location="Hải Phòng",
        salary_min_vnd=8_000_000,
    )
    best = lookup.fits[0]
    assert best.project.project_id == "rorze"
    assert best.score == 1.0
    assert [dimension.score for dimension in best.dimensions] == [1.0, 1.0, 1.0]

    cnc = next(fit for fit in lookup.fits if fit.project.project_id == "cnc")
    assert 0.0 < cnc.score < 1.0
    by_name = {dimension.name: dimension for dimension in cnc.dimensions}
    assert by_name["salary"].score == 1.0
    assert by_name["job_scope"].score in (0.0, 0.5)

    # A low fit is still in the ordered list — the answer unit is the project.
    assert {fit.project.project_id for fit in lookup.fits} == {
        project.project_id for project in _catalog(12)
    }


def test_rank_projects_scores_only_stated_preferences():
    unfiltered = rank_projects([_RORZE_LIKE])
    assert unfiltered.fits[0].score == 1.0
    assert unfiltered.fits[0].dimensions == ()

    partial = rank_projects([_RORZE_LIKE], location="Hải Phòng")
    assert len(partial.fits[0].dimensions) == 1
    assert partial.fits[0].score == 1.0


def test_rank_projects_unknown_fields_score_partial():
    blank = _project("blank", "Dự án trống")
    lookup = rank_projects(
        [blank],
        job_scope="lắp ráp",
        location="Hải Phòng",
        salary_min_vnd=10_000_000,
    )
    fit = lookup.fits[0]
    assert fit.score == 0.5
    by_name = {dimension.name: dimension for dimension in fit.dimensions}
    assert by_name["job_scope"].score == 0.5
    assert by_name["job_scope"].actual == ""
    assert by_name["location"].score == 0.5
    assert by_name["location"].actual == ""
    assert by_name["salary"].score == 0.5
    assert by_name["salary"].actual == ""


def test_rank_projects_salary_band_scores_full_partial_and_below():
    cases = [
        (14_000_000, 15_000_000, 1.0),  # ceiling covers the ask
        (8_400_000, 9_000_000, 0.5),  # within 80% of the ask
        (3_000_000, 4_000_000, 0.0),  # clearly below
    ]
    for salary_min, salary_max, expected in cases:
        project = _project(
            "p",
            "P",
            salary_min=salary_min,
            salary_max=salary_max,
        )
        fit = rank_projects([project], salary_min_vnd=10_000_000).fits[0]
        assert fit.dimensions[0].score == expected

    open_ceiling = _project("p", "P", salary_min=12_000_000, salary_max=None)
    fit = rank_projects([open_ceiling], salary_min_vnd=10_000_000).fits[0]
    assert fit.dimensions[0].score == 1.0


def test_rank_projects_company_is_a_hard_filter():
    lookup = rank_projects(_catalog(12), company="rorze")
    assert [fit.project.project_id for fit in lookup.fits] == ["rorze"]
    assert lookup.total == 1
    assert lookup.status == "matched"
    assert lookup.fits[0].dimensions[-1].name == "company"
    assert lookup.fits[0].dimensions[-1].score == 1.0


def test_rank_projects_company_filter_matching_nothing_is_empty_match():
    lookup = rank_projects(_catalog(12), company="không tồn tại")
    assert lookup.status == "matched"
    assert lookup.fits == ()
    assert lookup.total == 0


def test_rank_projects_sort_by_salary():
    projects = _catalog(12)
    desc = rank_projects(projects, sort_by="salary_desc")
    ceilings = [
        fit.project.salary_max if fit.project.salary_max is not None else -1
        for fit in desc.fits
    ]
    assert ceilings == sorted(ceilings, reverse=True)

    asc = rank_projects(projects, sort_by="salary_asc")
    floors = [
        fit.project.salary_min if fit.project.salary_min is not None else float("inf")
        for fit in asc.fits
    ]
    assert floors == sorted(floors)

    missing_last = _project("missing", "Thiếu lương")
    desc_with_missing = rank_projects([missing_last, _RORZE_LIKE], sort_by="salary_desc")
    assert desc_with_missing.fits[-1].project.project_id == "missing"
    asc_with_missing = rank_projects([missing_last, _RORZE_LIKE], sort_by="salary_asc")
    assert asc_with_missing.fits[-1].project.project_id == "missing"


def test_rank_projects_sort_by_timestamps():
    older = _project(
        "older", "A", updated_at=datetime(2026, 1, 1), salary_min=1, salary_max=2
    )
    newer = _project(
        "newer", "B", updated_at=datetime(2026, 6, 1), salary_min=1, salary_max=2
    )
    undated = _project("undated", "C", salary_min=1, salary_max=2)

    for sort_by in ("updated_at", "created_at"):
        lookup = rank_projects([undated, older, newer], sort_by=sort_by)
        assert [fit.project.project_id for fit in lookup.fits] == [
            "newer",
            "older",
            "undated",
        ]


def test_rank_projects_defaults_to_name_order_when_no_preferences():
    lookup = rank_projects(_catalog(12))
    names = [fit.project.name.casefold() for fit in lookup.fits]
    assert names == sorted(names)


def test_rank_projects_ties_break_by_name_ascending():
    twin_a = _project("a", "Dự án B", province="Hải Phòng")
    twin_b = _project("b", "Dự án A", province="Hải Phòng")
    lookup = rank_projects([twin_a, twin_b], location="Hải Phòng")
    assert [fit.project.name for fit in lookup.fits] == ["Dự án A", "Dự án B"]
