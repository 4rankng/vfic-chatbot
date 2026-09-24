"""SEC-05: the code-owned upload/body ceilings must actually be enforced.

The defect: ``assert_upload_size`` and the zip-bomb guard had no production call
site, and every upload route read the whole file into memory first, so the 20 MiB
cap was dead code. These tests pin the ceilings' values and prove the routes map
an over-limit upload to 413 *before* any extraction, persistence, or service work.

The routes are driven over HTTP on a bare app with a tiny ceiling patched into
``app.services.ingestion.limits`` (the value itself is pinned separately) so the
tests stay fast and deterministic.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge as knowledge_api
from app.api import personas as personas_api
from app.api.auth_dependencies import require_admin
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db
from app.services import ingestion
from app.services.ingestion import limits
from app.services.knowledge import KnowledgeService
from app.services.personas import PersonaService
from app.shared.infrastructure.db import get_request_db


def test_the_code_owned_ceilings_are_the_documented_values():
    assert limits.MAX_UPLOAD_BYTES == 20 * 1024 * 1024
    assert limits.MAX_WEBHOOK_BODY_BYTES == 1 * 1024 * 1024


@pytest.fixture
def tiny_upload_ceiling(monkeypatch) -> int:
    """Shrink the shared upload ceiling so a few bytes are already over it."""
    monkeypatch.setattr(limits, "MAX_UPLOAD_BYTES", 16)
    # assert_upload_size lives in the same module and reads the patched global.
    return 16


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_api.router, prefix="/api/v1")
    app.include_router(personas_api.router, prefix="/api/v1")
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_project_knowledge_db] = lambda: SimpleNamespace()
    app.dependency_overrides[get_request_db] = lambda: SimpleNamespace()
    return TestClient(app)


def test_knowledge_upload_file_rejects_an_oversized_upload(
    monkeypatch, tiny_upload_ceiling
) -> None:
    upload_bytes = AsyncMock()
    monkeypatch.setattr(KnowledgeService, "upload_bytes", upload_bytes)

    response = _client().post(
        "/api/v1/knowledge/documents/upload-file",
        files={"file": ("doc.md", b"x" * (tiny_upload_ceiling + 1), "text/markdown")},
    )

    assert response.status_code == 413
    upload_bytes.assert_not_awaited()


def test_kb_version_file_upload_rejects_an_oversized_upload(
    monkeypatch, tiny_upload_ceiling
) -> None:
    upload_text_file = AsyncMock()
    monkeypatch.setattr(KnowledgeService, "upload_text_file", upload_text_file)

    response = _client().post(
        f"/api/v1/knowledge/projects/{uuid.uuid4()}/kb/versions/{uuid.uuid4()}/files",
        files={"file": ("kb.md", b"x" * (tiny_upload_ceiling + 1), "text/markdown")},
    )

    assert response.status_code == 413
    upload_text_file.assert_not_awaited()


def test_persona_import_rejects_an_oversized_upload(monkeypatch, tiny_upload_ceiling) -> None:
    import_persona = AsyncMock()
    monkeypatch.setattr(PersonaService, "import_persona", import_persona)

    response = _client().post(
        "/api/v1/knowledge/personas/import",
        files={"file": ("persona.md", b"x" * (tiny_upload_ceiling + 1), "text/markdown")},
    )

    assert response.status_code == 413
    import_persona.assert_not_awaited()


def test_an_upload_at_the_ceiling_is_not_rejected_for_size(
    monkeypatch, tiny_upload_ceiling
) -> None:
    # The guard is a ceiling, not a strict inequality: an upload exactly at the
    # limit must reach the service layer.
    upload_bytes = AsyncMock(side_effect=RuntimeError("reached the service"))
    monkeypatch.setattr(KnowledgeService, "upload_bytes", upload_bytes)

    with pytest.raises(RuntimeError, match="reached the service"):
        _client().post(
            "/api/v1/knowledge/documents/upload-file",
            files={"file": ("doc.md", b"x" * tiny_upload_ceiling, "text/markdown")},
        )


def test_ingestion_limit_error_is_a_value_error():
    # The API layer relies on this to map the guard onto 413 without a wrapper.
    assert issubclass(ingestion.limits.IngestionLimitError, ValueError)
