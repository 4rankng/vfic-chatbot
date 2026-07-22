from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from socketio.exceptions import ConnectionRefusedError

from app.models.user import Role
from app.realtime import socketio as socketio_module


@pytest.mark.asyncio
async def test_socket_auth_prefers_handshake_token_over_bearer_header(monkeypatch) -> None:
    seen_tokens: list[str] = []

    async def fake_get_user_from_token(token: str, db) -> object:
        seen_tokens.append(token)
        return SimpleNamespace(id=uuid4(), role=Role.admin)

    monkeypatch.setattr(socketio_module, "get_user_from_token", fake_get_user_from_token)

    user = await socketio_module.authenticate_socket_token(
        {"token": "auth-token"},
        [(b"authorization", b"Bearer header-token")],
        SimpleNamespace(),
    )

    assert user.role == Role.admin
    assert seen_tokens == ["auth-token"]


@pytest.mark.asyncio
async def test_socket_auth_rejects_missing_token() -> None:
    with pytest.raises(ConnectionRefusedError) as exc_info:
        await socketio_module.authenticate_socket_token(None, [], SimpleNamespace())

    assert str(exc_info.value) == "authentication required"


@pytest.mark.asyncio
async def test_socket_auth_rejects_invalid_token(monkeypatch) -> None:
    async def fake_get_user_from_token(token: str, db) -> object:
        raise RuntimeError(token)

    monkeypatch.setattr(socketio_module, "get_user_from_token", fake_get_user_from_token)

    with pytest.raises(ConnectionRefusedError) as exc_info:
        await socketio_module.authenticate_socket_token(
            {"token": "bad-token"},
            [],
            SimpleNamespace(),
        )

    assert str(exc_info.value) == "invalid token"


@pytest.mark.asyncio
async def test_socket_connect_saves_session_and_joins_user_room(monkeypatch) -> None:
    user_id = uuid4()
    saved_sessions: list[tuple[str, dict[str, str]]] = []
    entered_rooms: list[tuple[str, str]] = []

    async def fake_authenticate_socket_token(auth, headers, db) -> object:
        return SimpleNamespace(id=user_id, role=Role.recruiter)

    @asynccontextmanager
    async def fake_async_session() -> AsyncIterator[object]:
        yield SimpleNamespace()

    async def fake_save_session(sid: str, session: dict[str, str]) -> None:
        saved_sessions.append((sid, session))

    async def fake_enter_room(sid: str, room: str) -> None:
        entered_rooms.append((sid, room))

    monkeypatch.setattr(
        socketio_module, "authenticate_socket_token", fake_authenticate_socket_token
    )
    monkeypatch.setattr(socketio_module.sio, "save_session", fake_save_session)
    monkeypatch.setattr(socketio_module.sio, "enter_room", fake_enter_room)

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "async_session", fake_async_session)

    await socketio_module.connect(
        "sid-1",
        {"asgi.scope": {"headers": [(b"authorization", b"Bearer ignored")]}},
        auth={"token": "socket-token"},
    )

    assert saved_sessions == [("sid-1", {"user_id": str(user_id), "role": "recruiter"})]
    assert entered_rooms == [("sid-1", f"user:{user_id}")]
