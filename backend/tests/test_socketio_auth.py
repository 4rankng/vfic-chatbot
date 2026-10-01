from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from socketio.exceptions import ConnectionRefusedError

from app.api.auth_dependencies import get_user_from_token
from app.identity.infrastructure import authentication
from app.models.user import Role
from app.realtime import socketio as socketio_module
from app.shared.domain.errors import UnauthorizedError


@pytest.fixture(autouse=True)
def clear_socket_access_state() -> None:
    socketio_module._connection_access.clear()


@pytest.mark.asyncio
async def test_socket_auth_prefers_handshake_token_over_bearer_header(monkeypatch) -> None:
    seen_tokens: list[str] = []

    async def fake_authenticate(token: str) -> object:
        seen_tokens.append(token)
        return SimpleNamespace(id=uuid4(), role=Role.admin)

    monkeypatch.setattr(
        socketio_module,
        "build_access_token_authenticator",
        lambda _db: SimpleNamespace(authenticate=fake_authenticate),
    )

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
    async def fake_authenticate(token: str) -> object:
        raise RuntimeError(token)

    monkeypatch.setattr(
        socketio_module,
        "build_access_token_authenticator",
        lambda _db: SimpleNamespace(authenticate=fake_authenticate),
    )

    with pytest.raises(ConnectionRefusedError) as exc_info:
        await socketio_module.authenticate_socket_token(
            {"token": "bad-token"},
            [],
            SimpleNamespace(),
        )

    assert str(exc_info.value) == "invalid token"


@pytest.mark.parametrize(
    ("token_type", "version", "disabled", "accepted"),
    [
        ("access", 3, False, True),
        ("access", 2, False, False),
        ("access", 3, True, False),
        ("refresh", 3, False, False),
    ],
)
async def test_socket_and_http_share_identity_validation(
    monkeypatch,
    token_type: str,
    version: int,
    disabled: bool,
    accepted: bool,
) -> None:
    user = SimpleNamespace(id=uuid4(), role=Role.recruiter, token_version=3, disabled=disabled)
    db = SimpleNamespace(get=AsyncMock(return_value=user))
    monkeypatch.setattr(
        authentication,
        "decode_token",
        AsyncMock(return_value={"type": token_type, "sub": str(user.id), "ver": version}),
    )

    if accepted:
        assert await get_user_from_token("token", db) is user
        socket_user = await socketio_module.authenticate_socket_token({"token": "token"}, [], db)
        assert socket_user is user
    else:
        with pytest.raises(UnauthorizedError):
            await get_user_from_token("token", db)
        with pytest.raises(ConnectionRefusedError, match="invalid token"):
            await socketio_module.authenticate_socket_token({"token": "token"}, [], db)


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
    access = socketio_module._connection_access["sid-1"]
    assert access.id == user_id
    assert access.role == Role.recruiter
