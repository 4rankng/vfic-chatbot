"""Repository-level contract tests for the income-summary read."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.recommendation import RecommendationRepository
from app.services.retrieval.repository import RetrievalRepository


@pytest.mark.asyncio
async def test_income_summary_for_active_projects_batches_relevant_feature_rows():
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(
            project_id="project-lg",
            project_slug="lg-display",
            project_name="LG Display",
            feature_key="take_home_income",
            category="income",
            name_vi="Thu nhập",
            value_text="Thu nhập thực tế 10-13 triệu/tháng khi có tăng ca, chưa bao gồm thưởng.",
            is_missing=False,
            needs_clarification=False,
        ),
        SimpleNamespace(
            project_id="project-rorze",
            project_slug="rorze",
            project_name="Rorze",
            feature_key="take_home_income",
            category="income",
            name_vi="Thu nhập",
            value_text=(
                "Thu nhập trung bình thực nhận theo tháng (có OVT, chưa bao gồm thưởng): "
                "14-15 triệu/tháng. Thu nhập trung bình theo năm (bao gồm thưởng): "
                "20-21 triệu/tháng."
            ),
            is_missing=False,
            needs_clarification=False,
        ),
        SimpleNamespace(
            project_id="project-rorze",
            project_slug="rorze",
            project_name="Rorze",
            feature_key="pay_frequency",
            category="cashflow",
            name_vi="Kỳ lương",
            value_text="Trả lương ngày 10 tháng sau.",
            is_missing=False,
            needs_clarification=False,
        ),
    ]
    db.execute = AsyncMock(return_value=result)

    outcome = await RecommendationRepository(db).income_summary_for_active_projects()

    assert [item.project_slug for item in outcome] == ["lg-display", "rorze"]
    assert "14-15 triệu/tháng" in outcome[1].evidence[0].value_text
    assert "20-21 triệu/tháng" in outcome[1].evidence[0].value_text
    assert outcome[1].evidence[1].feature_key == "pay_frequency"
    statement = db.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "worker_feature_catalog.feature_key IN" in sql
    assert "projects.is_active IS true" in sql
    assert "job_feature_values.is_missing IS false" in sql
    assert "job_feature_values.needs_clarification IS false" in sql
    assert "LIMIT" not in sql
    assert db.execute.await_count == 1


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
