"""Transport tests for the per-project external-API admin routes.

The app is assembled over a fake DB session (a real service), so the masking of
the sealed key is genuinely exercised end to end rather than stubbed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import projects as projects_api
from app.api.auth_dependencies import require_admin
from app.core.errors import register_domain_exception_handlers
from app.core.http import register_test_client
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db
from app.services.integration_settings.cipher import IntegrationSettingsCipher
from tests.test_project_external_api import (
    EXTERNAL_API_CLIENT_NAME,
    GUIDE,
    _FakeHttp,
    _FakeResponse,
    _FakeSession,
)

_BASE = "/api/v1/knowledge/projects"


@pytest.fixture
def client() -> tuple[TestClient, SimpleNamespace]:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(projects_api.router, prefix="/api/v1")
    holder = SimpleNamespace(db=None)
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_project_knowledge_db] = lambda: holder.db
    return TestClient(app), holder


def _configured_project(project_id: uuid.UUID, secret: str = "ttk_secret") -> SimpleNamespace:
    return SimpleNamespace(
        id=project_id,
        is_active=True,
        external_api={
            "enabled": True,
            "base_url": "https://api.example.com",
            "auth_header": "X-API-Key",
            "auth_scheme": "",
            "api_key_encrypted": IntegrationSettingsCipher().encrypt_with_context(
                secret, f"project-external-api:{project_id}"
            ),
            "guide": GUIDE,
        },
    )


def test_get_masks_the_api_key(client) -> None:
    http, holder = client
    project_id = uuid.uuid4()
    holder.db = _FakeSession(_configured_project(project_id))

    response = http.get(f"{_BASE}/{project_id}/external-api")

    assert response.status_code == 200
    body = response.json()
    assert body["api_key"] == {"configured": True, "preview": "10 ký tự"}
    assert body["enabled"] is True
    assert body["base_url"] == "https://api.example.com"
    assert body["auth_header"] == "X-API-Key"
    assert body["guide"] == GUIDE
    # The readiness projection degrades on the fake session instead of failing.
    assert body["chatbot_readiness"] == {
        "ready": False,
        "blockers": ["readiness_unavailable"],
    }
    # The sealed value must not appear anywhere in the wire payload.
    assert "api_key_encrypted" not in response.text
    assert "ttk_secret" not in response.text
    assert "v2:" not in response.text


def test_put_replaces_and_re_reads_the_view(client) -> None:
    http, holder = client
    project_id = uuid.uuid4()
    holder.db = _FakeSession(_configured_project(project_id))

    response = http.put(
        f"{_BASE}/{project_id}/external-api",
        json={
            "enabled": True,
            "base_url": "https://api.example.com/",
            "auth_header": "X-API-Key",
            "auth_scheme": "",
            "guide": GUIDE + "Bước 4: đặt lại mật khẩu.\n",
            "api_key": "ttk_fresh",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["base_url"] == "https://api.example.com"
    assert body["api_key"] == {"configured": True, "preview": "9 ký tự"}
    assert body["guide"].endswith("Bước 4: đặt lại mật khẩu.\n")
    assert holder.db.project.external_api["api_key_encrypted"].startswith("v2:")
    assert holder.db.commits == 1


def test_put_keeping_the_stored_key_when_api_key_is_omitted(client) -> None:
    http, holder = client
    project_id = uuid.uuid4()
    holder.db = _FakeSession(_configured_project(project_id))
    before = holder.db.project.external_api["api_key_encrypted"]

    response = http.put(
        f"{_BASE}/{project_id}/external-api",
        json={"enabled": True, "base_url": "https://api.example.com", "guide": GUIDE},
    )

    assert response.status_code == 200
    assert holder.db.project.external_api["api_key_encrypted"] == before
    assert response.json()["api_key"]["configured"] is True


def test_put_with_an_invalid_base_url_returns_the_machine_code(client) -> None:
    http, holder = client
    project_id = uuid.uuid4()
    holder.db = _FakeSession(_configured_project(project_id))

    response = http.put(
        f"{_BASE}/{project_id}/external-api",
        json={"enabled": True, "base_url": "http://api.example.com", "guide": GUIDE},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "base_url_scheme"


def test_put_enabled_without_a_guide_is_rejected(client) -> None:
    http, holder = client
    project_id = uuid.uuid4()
    holder.db = _FakeSession(_configured_project(project_id))

    response = http.put(
        f"{_BASE}/{project_id}/external-api",
        json={"enabled": True, "base_url": "https://api.example.com", "guide": ""},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "guide_required"


def test_post_test_call_routes_through_the_chatbot_egress_path(client) -> None:
    """The admin test call must hit the same egress path the bot uses."""
    http, holder = client
    project_id = uuid.uuid4()
    holder.db = _FakeSession(_configured_project(project_id))
    fake = _FakeHttp(response=_FakeResponse(200, '{"ok": true}'))
    register_test_client(EXTERNAL_API_CLIENT_NAME, fake)

    response = http.post(
        f"{_BASE}/{project_id}/external-api/test",
        json={"method": "GET", "path": "/health"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ok"
    assert body["status_code"] == 200
    assert body["detail"] == ""
    assert body["text"] == '{"ok": true}'
    # Exactly one outbound request, to the configured origin.
    assert len(fake.calls) == 1
    method, url, kwargs = fake.calls[0]
    assert method == "GET"
    assert url == "https://api.example.com/health"
    # auth_header + auth_scheme composed over the decrypted key.
    assert kwargs["headers"] == {"X-API-Key": "ttk_secret"}
