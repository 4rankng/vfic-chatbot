"""Tests for the external-source sync REST surface.

Hermetic: model-level invariants (Finding 6 FK guard, unique constraint) plus a
minimal TestClient that proves the API-layer SSRF gate rejects bad URLs before
any row is created. The full DB-backed lifecycle (create→stage→activate,
DELETE-leaves-chunks) belongs to the integration suite.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge as knowledge_api
from app.api.auth_dependencies import require_admin
from app.core.errors import register_domain_exception_handlers
from app.shared.infrastructure.db import get_request_db as get_db
from app.models.external_source_sync_state import ExternalSourceSyncState

VALID_URL = "https://docs.google.com/spreadsheets/d/1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8/edit"


# --------------------------------------------------------------------------- #
# Model invariants
# --------------------------------------------------------------------------- #


def test_last_revision_id_has_no_foreign_key() -> None:
    """Finding 6 regression guard: no FK on last_revision_id → DELETE can't cascade.

    Adding ``ForeignKey(..., ondelete="CASCADE")`` here would silently turn admin
    "Remove source" into wholesale published-FAQ deletion (because
    knowledge_documents/chunks.category_revision_id ARE ondelete=CASCADE). This
    test fails if anyone ever adds that FK.
    """
    column = ExternalSourceSyncState.__table__.columns["last_revision_id"]
    assert list(column.foreign_keys) == [], (
        "last_revision_id must NOT have a ForeignKey — see the model comment + "
        "docs/incident-runbook.md"
    )


def test_unique_constraint_present() -> None:
    constraints = {
        name
        for (name,) in (
            (c.name,) for c in ExternalSourceSyncState.__table__.constraints
        )
        if name
    }
    assert "uq_external_source_per_project_category_source" in constraints


# --------------------------------------------------------------------------- #
# API-layer SSRF gate (defense-in-depth, before any row is created)
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(knowledge_api.router, prefix="/api/v1")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid.uuid4())
    # A db that fails loudly if the rejection path ever reaches it.
    unsafe_db = AsyncMock()
    unsafe_db.add.side_effect = AssertionError("rejection path must not touch the DB")
    app.dependency_overrides[get_db] = lambda: unsafe_db
    return TestClient(app)


def test_create_rejects_non_google_url(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/external-sources",
        json={"category_key": "faq", "sheet_url": "https://evil.example/sheet.csv"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "host_not_allowed"


def test_create_rejects_http_url(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/external-sources",
        json={"category_key": "faq", "sheet_url": "http://docs.google.com/sheets/d/x/edit"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "scheme_not_https"


def test_create_rejects_ip_literal(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/external-sources",
        json={"category_key": "faq", "sheet_url": "https://169.254.169.254/latest/meta-data/"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ip_literal_forbidden"


def test_create_rejects_unknown_category_key(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/external-sources",
        json={"category_key": "nope", "sheet_url": VALID_URL},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_category_key"


def test_create_rejects_unsupported_source_kind(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/external-sources",
        json={
            "category_key": "faq",
            "sheet_url": VALID_URL,
            "source_kind": "evil_csv_host",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported_source_kind"
