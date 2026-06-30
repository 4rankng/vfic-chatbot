"""Router-layer tests for DELETE /{conv_id}/history (admin clear chat).

Pure unit tests — no live DB, no Redis. Uses httpx.ASGITransport + dependency
overrides on a standalone FastAPI instance (the real app is wrapped by
socketio.ASGIApp which lacks dependency_overrides).
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app.api.conversations import router as conversations_router
from app.api.dependencies import get_db, get_current_user

# Standalone FastAPI app with just the conversations router — avoids the
# socketio.ASGIApp wrapper that the real app.main exports.
_test_app = FastAPI()
_test_app.include_router(conversations_router, prefix="/api/v1")


def _make_user(role: str = "admin") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role, email=f"{role}@test.com")


def _make_conv() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="test-123",
        mode="human",
        status="open",
    )


@pytest.fixture()
def admin_user():
    return _make_user("admin")


@pytest.fixture()
def recruiter_user():
    return _make_user("recruiter")


@pytest.fixture()
def mock_db():
    db = AsyncMock()
    db.get = AsyncMock(return_value=_make_conv())
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture()
def transport(admin_user, mock_db):
    """ASGI transport with admin user + mock DB overrides."""

    async def override_user():
        return admin_user

    async def override_db():
        yield mock_db

    _test_app.dependency_overrides[get_current_user] = override_user
    _test_app.dependency_overrides[get_db] = override_db
    yield ASGITransport(app=_test_app)
    _test_app.dependency_overrides.clear()


@pytest.fixture()
def recruiter_transport(recruiter_user, mock_db):
    """ASGI transport with recruiter user + mock DB overrides."""

    async def override_user():
        return recruiter_user

    async def override_db():
        yield mock_db

    _test_app.dependency_overrides[get_current_user] = override_user
    _test_app.dependency_overrides[get_db] = override_db
    yield ASGITransport(app=_test_app)
    _test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_clear_history_returns_204(transport, mock_db):
    """Admin DELETE /{conv_id}/history → 204 No Content."""
    conv_id = str(mock_db.get.return_value.id)

    with patch(
        "app.api.conversations.ConversationService"
    ) as MockSvc:
        mock_svc_instance = AsyncMock()
        MockSvc.return_value = mock_svc_instance

        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.delete(
                f"/api/v1/conversations/{conv_id}/history"
            )

    assert resp.status_code == 204
    MockSvc.assert_called_once_with(mock_db)
    mock_svc_instance.clear_history.assert_called_once()


@pytest.mark.asyncio
async def test_recruiter_clear_history_returns_403(recruiter_transport):
    """Recruiter DELETE /{conv_id}/history → 403 Forbidden."""
    conv_id = str(uuid.uuid4())

    async with httpx.AsyncClient(
        transport=recruiter_transport, base_url="http://test"
    ) as client:
        resp = await client.delete(
            f"/api/v1/conversations/{conv_id}/history"
        )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_direct_get_hidden_when_not_visible(recruiter_transport, mock_db):
    """Direct UUID reads must use the same recruiter scope as list endpoints."""
    conv_id = str(uuid.uuid4())

    with patch("app.api.conversations.ConversationService") as MockSvc:
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_visible = AsyncMock(return_value=None)
        MockSvc.return_value = mock_svc_instance

        async with httpx.AsyncClient(
            transport=recruiter_transport, base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/conversations/{conv_id}")

    assert resp.status_code == 404
    mock_db.get.assert_not_called()
    mock_svc_instance.get_visible.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_history_returns_404_for_missing(admin_user, mock_db):
    """DELETE /{conv_id}/history → 404 when conversation doesn't exist."""
    mock_db.get = AsyncMock(return_value=None)
    conv_id = str(uuid.uuid4())

    async def override_user():
        return admin_user

    async def override_db():
        yield mock_db

    _test_app.dependency_overrides[get_current_user] = override_user
    _test_app.dependency_overrides[get_db] = override_db

    try:
        transport = ASGITransport(app=_test_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.delete(
                f"/api/v1/conversations/{conv_id}/history"
            )
        assert resp.status_code == 404
    finally:
        _test_app.dependency_overrides.clear()
