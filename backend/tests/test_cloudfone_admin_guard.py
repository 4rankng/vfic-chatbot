"""CHAT-15 permission matrix for the Cloudfone endpoints.

Set-up/config endpoints — GET/PUT ``/admin/integrations/cloudfone`` and the
POST ``/cloudfone/test`` probe — hold the CloudFone credentials and the daily
sync setup, so they answer 403 to anyone but an admin. The call-records view
(``/cloudfone/transcripts[...]``) is not admin territory: every projection
test in ``test_cloudfone_transcripts_api.py`` runs as a non-admin principal.

These tests drive the router over HTTP on a bare app and pin the config side
of the split: 403 for a recruiter, normal behavior for an admin.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import integrations as integrations_api
from app.api.auth_dependencies import get_current_user
from app.core.errors import register_domain_exception_handlers
from app.shared.infrastructure.db import get_request_db

_BASE = "/api/v1/admin/integrations/cloudfone"


class _MutableDb:
    """Typed double: no stored settings rows, plus the write surface updates use."""

    def __init__(self) -> None:
        self.rows: dict[str, object] = {}
        self.added: list = []

    async def scalars(self, _query):
        return SimpleNamespace(all=lambda: list(self.rows.values()))

    async def get(self, _model, key):
        return self.rows.get(key)

    def add(self, row) -> None:
        # Settings rows are keyed; audit events are not — keep both visible.
        key = getattr(row, "key", None)
        if key is not None:
            self.rows[key] = row
        self.added.append(row)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _client(role: str, session: _MutableDb | None = None) -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(integrations_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role=role
    )
    app.dependency_overrides[get_request_db] = lambda: session or _MutableDb()
    return TestClient(app)


def test_config_settings_reject_a_non_admin() -> None:
    client = _client("recruiter")

    assert client.get(_BASE).status_code == 403
    assert client.put(_BASE, json={"enabled": True}).status_code == 403


def test_config_test_connection_rejects_a_non_admin() -> None:
    client = _client("recruiter")

    assert client.post(f"{_BASE}/test", json={}).status_code == 403


def test_config_endpoints_serve_an_admin() -> None:
    db = _MutableDb()
    client = _client("admin", db)

    settings = client.get(_BASE)
    assert settings.status_code == 200
    assert settings.json()["auth_key"] == {"configured": False, "preview": None}

    # Unconfigured probe: fails fast with its missing list, never the vendor.
    probe = client.post(f"{_BASE}/test", json={})
    assert probe.status_code == 200
    body = probe.json()
    assert body["ok"] is False
    assert body["configured"] is False
    assert set(body["missing"]) == {"service_name", "auth_user", "auth_key"}

    # A full save stores the credentials and turns the feature on.
    saved = client.put(
        _BASE,
        json={
            "service_name": "CloudFone",
            "auth_user": "cf-user",
            "auth_key": "cf-key",
            "recipients": ["quanly@vp.vn"],
            "enabled": True,
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["enabled"] is True
    assert body["auth_user"] == "cf-user"
    assert body["auth_key"] == {"configured": True, "preview": "6 ký tự"}
    assert body["recipients"] == ["quanly@vp.vn"]
