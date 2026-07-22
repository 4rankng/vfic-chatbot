"""Repository-level contract tests for the ACTIVE-job availability query."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.models.company import Project
from app.services.recommendation import RecommendationRepository
from app.services.retrieval.repository import RetrievalRepository


@pytest.mark.asyncio
async def test_list_active_jobs_filters_to_active_positive_vacancies():
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = [
        (
            SimpleNamespace(
                id="job-1",
                title="Thợ hàn CO2",
                factory_name="Nhà máy A",
                province="Hải Phòng",
                district=None,
                salary_min=10_000_000,
                salary_max=14_000_000,
                vacancy_count=1,
            ),
            "Công ty A",
            ["CTA"],
            "Dự án A",
            "du-an-a",
            "project-a",
        )
    ]
    direct_result = MagicMock()
    direct_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(side_effect=[result, direct_result])

    outcome = await RecommendationRepository(db).list_active_jobs(role="thợ hàn CO2")

    assert outcome.status == "matched"
    assert outcome.jobs[0].id == "job-1"
    assert outcome.jobs[0].company_aliases == ("CTA",)
    assert outcome.jobs[0].project_name == "Dự án A"
    statement = db.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "jobs.status" in sql
    assert "coalesce(jobs.vacancy_count" in sql.lower()
    assert "projects.is_active IS true" in sql
    assert "jobs.updated_at DESC, jobs.id ASC" in sql


@pytest.mark.asyncio
async def test_list_active_jobs_includes_ready_single_page_project_without_job_rows():
    db = MagicMock()
    structured_result = MagicMock()
    structured_result.all.return_value = []
    project = Project(
        id="11111111-1111-4111-8111-111111111111",
        slug="rorze",
        name="Rorze",
        aliases=["Công ty Rorze"],
        is_active=True,
        summary="Tuyển nhân viên lắp ráp và vận hành máy CNC.",
        index_card={
            "roles": ["Nhân viên lắp ráp", "Nhân viên vận hành máy CNC"],
            "location": "KCN Nội Bài, Hà Nội",
            "highlights": ["Có đào tạo"],
        },
    )
    direct_result = MagicMock()
    direct_result.scalars.return_value.all.return_value = [project]
    db.execute = AsyncMock(side_effect=[structured_result, direct_result])

    outcome = await RecommendationRepository(db).list_active_jobs(role="lắp ráp", top_k=10)

    assert outcome.status == "matched"
    assert len(outcome.jobs) == 1
    assert outcome.jobs[0].id == str(project.id)
    assert outcome.jobs[0].title == "Nhân viên lắp ráp / Nhân viên vận hành máy CNC"
    assert outcome.jobs[0].company_name == "Rorze"
    assert outcome.jobs[0].province == "KCN Nội Bài, Hà Nội"
    assert outcome.jobs[0].project_slug == "rorze"
    direct_statement = db.execute.await_args_list[1].args[0]
    direct_sql = str(direct_statement.compile(dialect=postgresql.dialect()))
    assert "knowledge_base_direct_files" in direct_sql
    assert "knowledge_bases.mode" in direct_sql


@pytest.mark.asyncio
async def test_list_active_jobs_does_not_duplicate_single_page_project_with_structured_job():
    db = MagicMock()
    project_id = "11111111-1111-4111-8111-111111111111"
    structured_result = MagicMock()
    structured_result.all.return_value = [
        (
            SimpleNamespace(
                id="job-1",
                title="Nhân viên lắp ráp",
                factory_name="Rorze",
                province="Hà Nội",
                district=None,
                salary_min=None,
                salary_max=None,
                vacancy_count=None,
            ),
            "Rorze",
            [],
            "Rorze",
            "rorze",
            project_id,
        )
    ]
    direct_result = MagicMock()
    direct_result.scalars.return_value.all.return_value = [
        Project(
            id=project_id,
            slug="rorze",
            name="Rorze",
            is_active=True,
            summary="Tuyển nhân viên lắp ráp.",
            index_card={"roles": ["Nhân viên lắp ráp"]},
        )
    ]
    db.execute = AsyncMock(side_effect=[structured_result, direct_result])

    outcome = await RecommendationRepository(db).list_active_jobs(top_k=10)

    assert outcome.status == "matched"
    assert [job.id for job in outcome.jobs] == ["job-1"]


@pytest.mark.asyncio
async def test_list_active_jobs_keeps_single_page_project_in_bounded_mixed_catalog():
    db = MagicMock()
    structured_result = MagicMock()
    structured_result.all.return_value = [
        (
            SimpleNamespace(
                id=f"job-{index}",
                title=f"Công nhân {index}",
                factory_name="Nhà máy A",
                province="Hải Phòng",
                district=None,
                salary_min=None,
                salary_max=None,
                vacancy_count=None,
            ),
            "Công ty A",
            [],
            "Dự án A",
            "du-an-a",
            "project-a",
        )
        for index in range(10)
    ]
    direct_result = MagicMock()
    direct_result.scalars.return_value.all.return_value = [
        Project(
            id=f"11111111-1111-4111-8111-{index:012d}",
            slug=f"direct-{index}",
            name=f"Direct {index}",
            is_active=True,
            summary="Tuyển nhân viên lắp ráp.",
            index_card={"roles": ["Nhân viên lắp ráp"]},
        )
        for index in range(10)
    ]
    db.execute = AsyncMock(side_effect=[structured_result, direct_result])

    outcome = await RecommendationRepository(db).list_active_jobs(top_k=10)

    assert outcome.status == "matched"
    assert len(outcome.jobs) == 10
    assert [job.id for job in outcome.jobs[:4]] == [
        "11111111-1111-4111-8111-000000000000",
        "job-0",
        "11111111-1111-4111-8111-000000000001",
        "job-1",
    ]


@pytest.mark.asyncio
async def test_list_active_jobs_does_not_claim_roleless_single_page_project_is_hiring():
    db = MagicMock()
    structured_result = MagicMock()
    structured_result.all.return_value = []
    direct_result = MagicMock()
    direct_result.scalars.return_value.all.return_value = [
        Project(
            id="11111111-1111-4111-8111-111111111111",
            slug="information-only",
            name="Information Only",
            is_active=True,
            summary="Thông tin nhà máy.",
            index_card={"summary": "Thông tin nhà máy.", "roles": {"unexpected": "shape"}},
        )
    ]
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[structured_result, direct_result, catalog_result])

    outcome = await RecommendationRepository(db).list_active_jobs(top_k=10)

    assert outcome.status == "catalog_empty"
    assert outcome.jobs == ()


@pytest.mark.asyncio
async def test_list_active_jobs_can_be_scoped_to_knowledge_base_projects():
    db = MagicMock()
    active_result = MagicMock()
    active_result.all.return_value = []
    direct_result = MagicMock()
    direct_result.scalars.return_value.all.return_value = []
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[active_result, direct_result, catalog_result])

    outcome = await RecommendationRepository(db).list_active_jobs(
        role="thợ hàn CO2", project_ids=["project-a", "project-b"]
    )

    assert outcome.status == "catalog_empty"
    statement = db.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "companies.project_id IN" in sql


@pytest.mark.asyncio
async def test_nonempty_catalog_with_no_open_jobs_is_a_real_no_match():
    db = MagicMock()
    active_result = MagicMock()
    active_result.all.return_value = []
    direct_result = MagicMock()
    direct_result.scalars.return_value.all.return_value = []
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none.return_value = "inactive-job-id"
    db.execute = AsyncMock(side_effect=[active_result, direct_result, catalog_result])

    outcome = await RecommendationRepository(db).list_active_jobs(
        company="LG", location="Tràng Duệ", project_ids=["project-a"]
    )

    assert outcome.status == "no_match"
    assert db.execute.await_count == 3


@pytest.mark.asyncio
async def test_list_active_jobs_with_no_active_agent_projects_reports_empty_catalog():
    db = MagicMock()
    db.execute = AsyncMock()

    outcome = await RecommendationRepository(db).list_active_jobs(
        company="LG", location="Tràng Duệ", project_ids=[]
    )

    assert outcome.status == "catalog_empty"
    assert outcome.jobs == ()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_active_jobs_returns_unavailable_on_database_error():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    db.rollback = AsyncMock()

    outcome = await RecommendationRepository(db).list_active_jobs(role="thợ hàn CO2")

    assert outcome.status == "unavailable"
    assert outcome.jobs == ()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieval_active_job_lookup_scopes_to_active_agent_kb_projects(monkeypatch):
    class _Db:
        async def scalars(self, _statement):
            return ["project-a", "project-b"]

    captured: dict[str, object] = {}

    async def list_active_jobs(
        self, *, role, company, location, top_k, project_ids
    ):
        captured.update(
            role=role,
            company=company,
            location=location,
            top_k=top_k,
            project_ids=project_ids,
        )
        return SimpleNamespace(status="no_match", jobs=())

    monkeypatch.setattr(RecommendationRepository, "list_active_jobs", list_active_jobs)

    result = await RetrievalRepository(_Db()).list_active_jobs(
        role="thợ hàn",
        company="LG",
        location="Hải Phòng",
        top_k=2,
    )

    assert result.status == "no_match"
    assert captured == {
        "role": "thợ hàn",
        "company": "LG",
        "location": "Hải Phòng",
        "top_k": 2,
        "project_ids": ["project-a", "project-b"],
    }


@pytest.mark.asyncio
async def test_retrieval_active_project_failure_returns_unavailable():
    class _Db:
        async def scalars(self, _statement):
            raise RuntimeError("db down")

    result = await RetrievalRepository(_Db()).list_active_jobs(role="thợ hàn")

    assert result.status == "unavailable"
    assert result.jobs == ()


@pytest.mark.asyncio
async def test_project_slug_lookup_uses_project_owned_knowledge_base():
    captured: dict[str, object] = {}

    class _Db:
        async def execute(self, statement, params):
            captured.update(sql=str(statement), params=params)
            return SimpleNamespace(scalar_one_or_none=lambda: "project-a")

    project_id = await RetrievalRepository(_Db()).project_id_by_slug(
        "factory-a", active_only=True
    )

    assert project_id == "project-a"
    assert "p.knowledge_base_id IS NOT NULL" in captured["sql"]
    assert "JOIN personas" not in captured["sql"]
    assert "p.is_active" in captured["sql"]
