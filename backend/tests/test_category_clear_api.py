"""Clear transport keeps manual behavior and validates migration preconditions."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

from fastapi import FastAPI
import httpx
import pytest

from app.api import projects
from app.models.knowledge import KnowledgeCategoryRevisionStatus
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.schemas.project_knowledge import CategoryClearRequest


def _service(monkeypatch):
    revision = SimpleNamespace(
        id=uuid.uuid4(),
        category_id=uuid.uuid4(),
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.CLEARED,
        source_filename="jobs.md",
        content_sha256="a" * 64,
        normalized_payload={"schema_version": "1.0", "category": "jobs", "jobs": []},
        created_at=datetime.now(UTC),
    )
    service = SimpleNamespace(clear=AsyncMock(return_value=revision))
    monkeypatch.setattr(projects, "KnowledgeCategoryService", lambda db: service)
    return service


@pytest.mark.parametrize(
    "query,expected,status",
    [("", None, 200), ("?expected_revision_no=0", 0, 200), ("?expected_revision_no=-1", None, 422)],
)
async def test_clear_api_validates_and_forwards_optional_precondition(
    monkeypatch, query, expected, status
) -> None:
    service = _service(monkeypatch)
    app = FastAPI()
    app.include_router(projects.router)
    actor, db = object(), object()
    app.dependency_overrides[projects.require_admin] = lambda: actor
    app.dependency_overrides[projects.get_project_knowledge_db] = lambda: db
    project_id = uuid.uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/knowledge/projects/{project_id}/categories/jobs/clear{query}",
            json={"confirmation": "CLEAR"},
        )
    assert response.status_code == status
    if status == 200:
        service.clear.assert_awaited_once_with(
            project_id=project_id,
            category_key=KnowledgeCategoryKey.JOBS,
            actor=actor,
            expected_revision_no=expected,
        )
    else:
        service.clear.assert_not_awaited()


async def test_direct_clear_call_defaults_to_no_precondition(monkeypatch) -> None:
    service = _service(monkeypatch)
    await projects.clear_project_category(
        uuid.uuid4(),
        KnowledgeCategoryKey.JOBS,
        CategoryClearRequest(confirmation="CLEAR"),
        admin=object(),
        db=object(),
    )
    assert service.clear.await_args.kwargs["expected_revision_no"] is None
