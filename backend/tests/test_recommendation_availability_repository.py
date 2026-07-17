"""Repository-level contract tests for the ACTIVE-job availability query."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

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
        )
    ]
    db.execute = AsyncMock(return_value=result)

    outcome = await RecommendationRepository(db).list_active_jobs(role="thợ hàn CO2")

    assert outcome.status == "matched"
    assert outcome.jobs[0].id == "job-1"
    assert outcome.jobs[0].company_aliases == ("CTA",)
    assert outcome.jobs[0].project_name == "Dự án A"
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "jobs.status" in sql
    assert "coalesce(jobs.vacancy_count" in sql.lower()
    assert "projects.is_active IS true" in sql
    assert "jobs.updated_at DESC, jobs.id ASC" in sql


@pytest.mark.asyncio
async def test_list_active_jobs_can_be_scoped_to_knowledge_base_projects():
    db = MagicMock()
    active_result = MagicMock()
    active_result.all.return_value = []
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[active_result, catalog_result])

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
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none.return_value = "inactive-job-id"
    db.execute = AsyncMock(side_effect=[active_result, catalog_result])

    outcome = await RecommendationRepository(db).list_active_jobs(
        company="LG", location="Tràng Duệ", project_ids=["project-a"]
    )

    assert outcome.status == "no_match"
    assert db.execute.await_count == 2


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
async def test_project_slug_lookup_stays_inside_active_agent_knowledge_base():
    captured: dict[str, object] = {}

    class _Db:
        async def execute(self, statement, params):
            captured.update(sql=str(statement), params=params)
            return SimpleNamespace(scalar_one_or_none=lambda: "project-a")

    project_id = await RetrievalRepository(_Db()).project_id_by_slug(
        "factory-a", active_only=True
    )

    assert project_id == "project-a"
    assert "JOIN personas pe ON pe.knowledge_base_id = p.knowledge_base_id" in captured["sql"]
    assert "p.is_active" in captured["sql"]
