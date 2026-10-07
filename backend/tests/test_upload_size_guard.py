"""SEC-05 + SEC-10: the code-owned upload/body ceilings must actually be enforced.

The defect: ``assert_upload_size`` and the zip-bomb guard had no production call
site, and every upload route read the whole file into memory first, so the 20 MiB
cap was dead code. SEC-10 closed the second half: even with the guard in place,
``await file.read()`` pulled the entire body into one allocation *before* the
length was compared. The routes now read through ``read_upload_within_limit``,
which reads at most ceiling+1 bytes.

The routes are driven over HTTP on a bare app with a tiny ceiling patched into
``app.services.ingestion.limits`` (the value itself is pinned separately) so the
tests stay fast and deterministic.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import knowledge as knowledge_api
from app.api.auth_dependencies import require_admin
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db
from app.services import ingestion
from app.services.ingestion import limits
from app.services.knowledge import KnowledgeService
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


class _RecordingUpload:
    """UploadFile double that records the size argument of every ``read``."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.payload if size < 0 else self.payload[:size]


@pytest.mark.asyncio
async def test_a_body_one_byte_over_the_ceiling_is_rejected_without_reading_it_whole(
    tiny_upload_ceiling,
) -> None:
    # SEC-10: the old `await file.read()` pulled the entire body into one
    # allocation and only then compared its length. The bounded read asks for
    # ceiling+1 bytes, so the oversized payload is never materialized whole.
    upload = _RecordingUpload(b"x" * (tiny_upload_ceiling + 10_000))

    with pytest.raises(HTTPException) as exc:
        await limits.read_upload_within_limit(upload)

    assert exc.value.status_code == 413
    assert upload.read_sizes == [tiny_upload_ceiling + 1]


@pytest.mark.asyncio
async def test_a_body_exactly_at_the_ceiling_is_read_and_returned(tiny_upload_ceiling) -> None:
    upload = _RecordingUpload(b"x" * tiny_upload_ceiling)

    data = await limits.read_upload_within_limit(upload)

    assert data == b"x" * tiny_upload_ceiling
    assert upload.read_sizes == [tiny_upload_ceiling + 1]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/knowledge/documents/upload-file",
        "/api/v1/knowledge/documents/extract-text",
    ],
)
def test_the_rejection_detail_is_the_same_on_every_upload_route(path, tiny_upload_ceiling) -> None:
    response = _client().post(
        path,
        files={"file": ("doc.md", b"x" * (tiny_upload_ceiling + 1), "text/markdown")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == limits.upload_too_large_detail()
