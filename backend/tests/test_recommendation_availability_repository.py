"""Repository-level contract tests for the ACTIVE-job availability query."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.recommendation import RecommendationRepository


@pytest.mark.asyncio
async def test_find_active_jobs_filters_to_active_positive_vacancies():
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
        )
    ]
    db.execute = AsyncMock(return_value=result)

    outcome = await RecommendationRepository(db).find_active_jobs("thợ hàn CO2")

    assert outcome.status == "matched"
    assert outcome.jobs[0].id == "job-1"
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "jobs.status" in sql
    assert "coalesce(jobs.vacancy_count" in sql.lower()


@pytest.mark.asyncio
async def test_find_active_jobs_returns_unavailable_on_database_error():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    db.rollback = AsyncMock()

    outcome = await RecommendationRepository(db).find_active_jobs("thợ hàn CO2")

    assert outcome.status == "unavailable"
    assert outcome.jobs == ()
    db.rollback.assert_awaited_once()
