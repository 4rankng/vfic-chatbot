"""Contract tests for the rich project-catalog read behind the match tool.

``CatalogRepository.list_active_projects`` is the matching authority's data
seam: EVERY active KB-backed project as :class:`ProjectFeatures` — structured
scope items from open Job rows, or card + ``take_home_income`` features for
card-only projects. No caps, no answer-unit jobs.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.retrieval.catalog_repository import CatalogRepository


def _project_row(
    name: str,
    *,
    slug: str | None = None,
    card: dict | None = None,
    summary: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        slug=slug or name.lower().replace(" ", "-"),
        name=name,
        summary=summary,
        index_card=card or {},
        updated_at=None,
        latitude=latitude,
        longitude=longitude,
    )


def _job_row(
    *,
    project_id,
    title: str,
    company_name: str = "Công ty",
    factory_name: str = "",
    province: str = "",
    district: str = "",
    address: str = "",
    salary_min=None,
    salary_max=None,
):
    return SimpleNamespace(
        title=title,
        salary_min=salary_min,
        salary_max=salary_max,
        province=province,
        district=district,
        address=address,
        factory_name=factory_name,
        company_name=company_name,
        project_id=project_id,
    )


def _db_with(*results) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


def _result(rows) -> MagicMock:
    result = MagicMock()
    result.all.return_value = list(rows)
    return result


async def _features(db, **kwargs):
    return await CatalogRepository(
        db, page_project_ids=kwargs.pop("page_project_ids", None), **kwargs
    ).list_active_projects()


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


@pytest.mark.asyncio
async def test_catalog_read_is_restricted_to_active_kb_gated_projects():
    db = _db_with(_result([]), _result([]))

    assert await _features(db) == []

    project_sql = _sql(db.execute.await_args_list[0].args[0])
    assert "projects.is_active IS true" in project_sql
    assert "projects.knowledge_base_id IS NOT NULL" in project_sql
    assert "LIMIT" not in project_sql


@pytest.mark.asyncio
async def test_catalog_read_keeps_linked_projects_first_but_never_exclusive():
    """Operator directive 2026-10-07: the Page's linked projects are the
    catalog's starting point, never its ceiling — every active KB-backed
    project comes back, ordered linked-first, so the bot can consult other
    projects when the candidate asks."""
    linked = _project_row("LG Display", card={"roles": ["Nhân viên lắp ráp"]})
    other = _project_row("AMTRAN", card={"roles": ["Công nhân lắp ráp"]})
    db = _db_with(_result([linked, other]), _result([]), _result([]))

    features = await _features(db, page_project_ids=(str(linked.id),))

    assert [row.name for row in features] == ["LG Display", "AMTRAN"]

    project_sql = _sql(db.execute.await_args_list[0].args[0])
    where_clause, order_clause = project_sql.split("ORDER BY")
    assert "projects.id IN" not in where_clause
    assert "THEN 0 ELSE 1" in order_clause


@pytest.mark.asyncio
async def test_structured_scope_rows_carry_the_open_vacancy_predicate():
    project = _project_row("LG Display")
    db = _db_with(
        _result([project]),
        _result(
            [
                _job_row(
                    project_id=project.id,
                    title="Công nhân sản xuất",
                    company_name="LG Display",
                    factory_name="Nhà máy Tràng Duệ",
                    province="Hải Phòng",
                    salary_min=8_000_000,
                    salary_max=12_000_000,
                )
            ]
        ),
    )

    features = await _features(db)

    assert len(features) == 1
    row = features[0]
    assert row.name == "LG Display"
    assert [item.title for item in row.scope] == ["Công nhân sản xuất"]
    assert (row.salary_min, row.salary_max) == (8_000_000, 12_000_000)
    assert row.company == "LG Display"
    assert row.factory == "Nhà máy Tràng Duệ"
    assert row.province == "Hải Phòng"

    job_sql = _sql(db.execute.await_args_list[1].args[0])
    assert "jobs.status" in job_sql
    assert "coalesce(jobs.vacancy_count" in job_sql.lower()
    assert "jobs.source_category_revision_id" in job_sql
    assert "projects.category_authority_started" in job_sql
    assert "knowledge_categories.active_revision_id = jobs.source_category_revision_id" in job_sql
    assert "knowledge_categories.category_key = 'jobs'" in job_sql
    assert "EXISTS" in job_sql
    assert "LIMIT" not in job_sql


@pytest.mark.asyncio
async def test_structured_scope_aggregates_item_salaries_and_first_locations():
    project = _project_row("Rorze")
    db = _db_with(
        _result([project]),
        _result(
            [
                _job_row(
                    project_id=project.id,
                    title="Nhân viên lắp ráp",
                    province="Hải Phòng",
                    salary_min=6_300_000,
                    salary_max=10_000_000,
                ),
                _job_row(
                    project_id=project.id,
                    title="Nhân viên vận hành máy CNC",
                    address="KCN Nội Bài",
                    salary_min=7_000_000,
                    salary_max=11_000_000,
                ),
            ]
        ),
    )

    row = (await _features(db))[0]
    assert [(item.title, item.salary_min, item.salary_max) for item in row.scope] == [
        ("Nhân viên lắp ráp", 6_300_000, 10_000_000),
        ("Nhân viên vận hành máy CNC", 7_000_000, 11_000_000),
    ]
    assert (row.salary_min, row.salary_max) == (6_300_000, 11_000_000)
    assert (row.province, row.district, row.address) == ("Hải Phòng", "", "KCN Nội Bài")


@pytest.mark.asyncio
async def test_card_only_project_features_come_from_card_and_take_home_income():
    project = _project_row(
        "Rorze",
        slug="rorze",
        card={
            "roles": ["Nhân viên lắp ráp", "Nhân viên vận hành máy CNC"],
            "location": "KCN Nội Bài, Hà Nội",
        },
    )
    salary_row = SimpleNamespace(
        project_id=project.id,
        value_json={"min": 10_000_000, "max": 13_000_000, "currency": "VND"},
    )
    db = _db_with(_result([project]), _result([]), _result([salary_row]))

    features = await _features(db)

    assert len(features) == 1
    row = features[0]
    assert (row.project_id, row.slug, row.name) == (str(project.id), "rorze", "Rorze")
    assert [item.title for item in row.scope] == [
        "Nhân viên lắp ráp",
        "Nhân viên vận hành máy CNC",
    ]
    assert all(item.salary_min is None and item.salary_max is None for item in row.scope)
    assert row.province == "KCN Nội Bài, Hà Nội"
    assert (row.salary_min, row.salary_max) == (10_000_000, 13_000_000)

    salary_sql = _sql(db.execute.await_args_list[2].args[0])
    assert "take_home_income" in salary_sql


@pytest.mark.asyncio
async def test_card_only_project_falls_back_to_card_salary_fields():
    project = _project_row(
        "Rorze",
        card={
            "roles": ["Nhân viên lắp ráp"],
            "location": "Hà Nội",
            "salary_min_vnd": 9_000_000,
            "salary_max_vnd": "12.000.000",
        },
    )
    db = _db_with(_result([project]), _result([]), _result([]))

    row = (await _features(db))[0]
    assert (row.salary_min, row.salary_max) == (9_000_000, 12_000_000)


@pytest.mark.asyncio
async def test_catalog_keeps_recruiter_aliases_for_named_project_matching():
    project = _project_row("LG Display", card={"roles": ["Lắp ráp"]})
    project.aliases = ["LGD", "LG D"]
    db = _db_with(_result([project]), _result([]), _result([]))

    row = (await _features(db))[0]

    assert row.aliases == ("LGD", "LG D")
    assert "projects.aliases" in _sql(db.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_catalog_carries_project_coordinates_for_distance_evidence():
    """The geo-distance read rides the catalog select for both feature shapes."""
    structured = _project_row("Tràng Duệ", latitude=20.86, longitude=106.68)
    db = _db_with(
        _result([structured]),
        _result(
            [
                _job_row(
                    project_id=structured.id,
                    title="Nhân viên lắp ráp",
                    province="Hải Phòng",
                )
            ]
        ),
        _result([]),
    )

    row = (await _features(db))[0]

    assert (row.latitude, row.longitude) == (20.86, 106.68)
    select_sql = _sql(db.execute.await_args_list[0].args[0])
    assert "projects.latitude" in select_sql
    assert "projects.longitude" in select_sql

    card_only = _project_row("Rorze", card={"roles": ["Lắp ráp"]})
    db = _db_with(_result([card_only]), _result([]), _result([]))

    assert (await _features(db))[0].latitude is None


@pytest.mark.asyncio
async def test_card_only_project_coerces_string_salaries_from_llm():
    project = _project_row(
        "String Salary Co",
        card={"roles": ["Công nhân"], "location": "Hải Phòng"},
    )
    salary_row = SimpleNamespace(
        project_id=project.id,
        value_json={"min": "10000000", "max": "13000000"},
    )
    db = _db_with(_result([project]), _result([]), _result([salary_row]))

    row = (await _features(db))[0]
    assert (row.salary_min, row.salary_max) == (10_000_000, 13_000_000)


@pytest.mark.asyncio
async def test_project_with_structured_jobs_is_not_duplicated():
    project = _project_row(
        "Rorze",
        card={"roles": ["Nhân viên lắp ráp"], "location": "Hà Nội"},
    )
    db = _db_with(
        _result([project]),
        _result(
            [
                _job_row(
                    project_id=project.id,
                    title="Nhân viên lắp ráp",
                    company_name="Rorze",
                    province="Hà Nội",
                )
            ]
        ),
    )

    features = await _features(db)

    assert len(features) == 1
    assert [item.title for item in features[0].scope] == ["Nhân viên lắp ráp"]


@pytest.mark.asyncio
async def test_twelve_projects_produce_twelve_rows():
    projects = [_project_row(f"Dự án {index:02d}") for index in range(12)]
    db = _db_with(_result(projects), _result([]), _result([]))

    features = await _features(db)

    assert len(features) == 12
    assert [row.name for row in features] == [f"Dự án {index:02d}" for index in range(12)]
    # Roleless projects stay in the catalog: the answer unit is the project.
    assert all(row.scope == () for row in features)


@pytest.mark.asyncio
async def test_database_errors_propagate_for_the_tool_to_map():
    db = _db_with()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))

    with pytest.raises(RuntimeError):
        await _features(db)


def _one_result(row) -> MagicMock:
    result = MagicMock()
    result.one.return_value = row
    return result


@pytest.mark.asyncio
async def test_active_area_viewbox_pads_the_project_bounding_box():
    """The bias box must comfortably contain the landmarks candidates name near
    the projects, not only the projects themselves (margin ≈ 38 km)."""
    db = MagicMock()
    db.execute = AsyncMock(return_value=_one_result((20.80, 21.00, 106.50, 106.90)))

    box = await CatalogRepository(db, page_project_ids=None).active_area_viewbox()

    assert box == "106.1500,21.3500,107.2500,20.4500"


@pytest.mark.asyncio
async def test_active_area_viewbox_is_none_without_coordinates():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_one_result((None, None, None, None)))

    assert await CatalogRepository(db, page_project_ids=None).active_area_viewbox() is None
