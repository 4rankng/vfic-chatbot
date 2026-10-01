"""The saved-knowledge download is distinct from a template and admin-only."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import projects
from app.api.auth_dependencies import get_current_user
from app.core.errors import register_domain_exception_handlers
from app.shared.domain.errors import ConflictError, NotFoundError
from app.services.project.knowledge_export import _export_filename


@pytest.fixture
def export_api(monkeypatch):
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(projects.router)
    app.dependency_overrides[projects.get_project_knowledge_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="admin")
    export = AsyncMock(
        return_value=SimpleNamespace(
            filename="kb-xuong-hai-phong.md",
            content="# Kiến thức dự án\n\nLương cơ bản: 6.000.000 đồng.\n",
        )
    )
    monkeypatch.setattr(
        projects,
        "ProjectService",
        lambda _db: SimpleNamespace(
            export_knowledge=export,
        ),
    )
    with TestClient(app) as client:
        yield app, client, export


def test_admin_downloads_utf8_markdown_saved_source(export_api):
    _app, client, export = export_api
    project_id = uuid.uuid4()

    response = client.get(f"/knowledge/projects/{project_id}/knowledge-export")

    assert response.status_code == 200
    assert response.content == export.return_value.content.encode("utf-8")
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="kb-xuong-hai-phong.md"'
    )
    assert response.headers["cache-control"] == "no-store"
    export.assert_awaited_once_with(project_id)


@pytest.mark.parametrize("role", ["recruiter", "unknown"])
def test_export_denies_non_admin_before_reading_sources(export_api, role):
    app, client, export = export_api
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role)

    response = client.get(f"/knowledge/projects/{uuid.uuid4()}/knowledge-export")

    assert response.status_code == 403
    export.assert_not_awaited()


def test_export_requires_authentication(export_api):
    app, client, export = export_api
    app.dependency_overrides.pop(get_current_user)

    response = client.get(f"/knowledge/projects/{uuid.uuid4()}/knowledge-export")

    assert response.status_code == 401
    export.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (NotFoundError("Project not found"), 404),
        (ConflictError("Dự án chưa có kiến thức đang sử dụng để xuất."), 409),
    ],
)
def test_export_returns_explicit_missing_or_empty_error(export_api, error, expected_status):
    _app, client, export = export_api
    export.side_effect = error

    response = client.get(f"/knowledge/projects/{uuid.uuid4()}/knowledge-export")

    assert response.status_code == expected_status
    assert response.json() == {"detail": error.detail}
    assert "content-disposition" not in response.headers


def test_export_validates_project_id_before_delegating(export_api):
    _app, client, export = export_api

    response = client.get("/knowledge/projects/not-a-uuid/knowledge-export")

    assert response.status_code == 422
    export.assert_not_awaited()


@pytest.mark.parametrize(
    "slug",
    [
        '../"\r\nX-Evil: value/\\source',
        "Dự án Hải Phòng",
        "CON",
        "",
        "💼",
        "x" * 400,
    ],
)
def test_download_filename_cannot_inject_headers_or_paths(slug):
    import re

    filename = _export_filename(slug, uuid.UUID("cfdd1d8b-f8f9-4c5e-9a1f-6410ec2c2b16"))

    assert re.fullmatch(r"kb-[a-z0-9_-]{1,80}\.md", filename)
    assert len(filename) <= 86


def test_download_filename_keeps_ordinary_project_slug():
    assert _export_filename("e2e-saved-knowledge", uuid.uuid4()) == "kb-e2e-saved-knowledge.md"


def test_export_openapi_declares_markdown_attachment(export_api):
    app, _client, _export = export_api

    response = app.openapi()["paths"]["/knowledge/projects/{project_id}/knowledge-export"]["get"][
        "responses"
    ]["200"]

    assert response["content"] == {"text/markdown": {"schema": {"type": "string"}}}
