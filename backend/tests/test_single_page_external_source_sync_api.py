from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api import projects as projects_api
from app.api.dependencies import get_db, require_admin
from app.core.errors import register_domain_exception_handlers
from app.shared.domain.errors import ConflictError
from app.main import app as main_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(projects_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid.uuid4())
    return TestClient(app)


def test_route_is_admin_only() -> None:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(projects_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[require_admin] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail="admin only")
    )

    response = TestClient(app).get(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/single-page/external-sources"
    )
    assert response.status_code == 403


@pytest.mark.parametrize("error_code", ["missing_gid", "invalid_sheet_id", "url_credentials_forbidden"])
def test_create_maps_source_url_contract_errors_to_bad_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
    , error_code: str
) -> None:
    monkeypatch.setattr(
        projects_api.ProjectService,
        "create_single_page_external_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConflictError(error_code)),
    )

    response = client.post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/single-page/external-sources",
        json={"sheet_url": "https://docs.google.com/spreadsheets/d/x/edit", "auto_sync_enabled": True},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == error_code


def test_run_now_maps_cooldown_to_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        projects_api.ProjectService,
        "run_single_page_external_source_now",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConflictError("run_now_cooldown")),
    )

    response = client.post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/single-page/external-sources/{uuid.uuid4()}/run-now"
    )
    assert response.status_code == 429
    assert response.json()["detail"] == "run_now_cooldown"


def test_openapi_contains_new_single_page_routes_and_existing_rag_routes() -> None:
    fastapi_app = getattr(main_app, "other_asgi_app", main_app)
    paths = fastapi_app.openapi()["paths"]
    assert "/api/v1/knowledge/projects/{project_id}/single-page/external-sources" in paths
    assert (
        "/api/v1/knowledge/projects/{project_id}/single-page/external-sources/{source_id}/run-now"
        in paths
    )
    assert "/api/v1/knowledge/projects/{project_id}/external-sources" in paths
