"""Socket.IO realtime server (replaces the SSE firehose for chat).

A single AsyncServer fronts the web process. It is mounted at the ASGI root
(``socketio.ASGIApp`` with ``other_asgi_app=fastapi``) so Socket.IO traffic on
``/socket.io/`` is served alongside the REST API. The server uses an
``AsyncRedisManager`` so emits published by OTHER processes (the RQ
worker-chatbot, which records bot outcomes) over the same Redis bus are fanned
out to the browser sockets held by THIS process.

Auth: the browser connects with ``{ auth: { token } }``; the connect handler
verifies the access JWT via the same identity authenticator used by REST,
refuses on failure, and rooms the connection by user and (on demand) by
conversation. This replaces the SSE ``?token=`` workaround.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

import socketio
from socketio.exceptions import ConnectionRefusedError

from app.core.config import get_settings
from app.identity.infrastructure.authentication import build_access_token_authenticator
from app.models.user import Role
from app.services.viewer_scope import (
    viewer_can_access_conversation,
    viewer_can_access_lead,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _room_for_payload(payload: dict) -> str | None:
    """The Socket.IO room a realtime event targets.

    Conversation events carry ``conversation_id`` or ``id`` → ``conv:{id}``.
    Lead events carry ``lead_id`` → ``lead:{id}``.
    Events with neither are unroutable. Publishers must suppress them rather
    than treating ``None`` as a broadcast room.
    """
    if payload.get("lead_id") is not None:
        lead_id = _lead_id(payload["lead_id"])
        return f"lead:{lead_id}" if lead_id is not None else None
    conversation_id = _conversation_id(payload.get("conversation_id") or payload.get("id"))
    if conversation_id is None:
        return None
    return f"conv:{conversation_id}"


# AsyncRedisManager: shared Redis bus so emits from other processes (RQ worker)
# reach sockets held by this web process. Constructing it does NOT open a
# background listener (that starts on ASGI lifespan, which the test suite does
# not run), so importing this module in tests leaks no loop-bound connections.
sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(settings.redis_url),
    cors_allowed_origins=settings.cors_origins_list,
    cors_credentials=True,
    transports=["websocket", "polling"],
    async_handlers=True,
)

_SocketHandler = TypeVar("_SocketHandler", bound=Callable[..., Awaitable[object]])


def _socket_event(name: str) -> Callable[[_SocketHandler], _SocketHandler]:
    """Use the decorator form of Socket.IO's handler-or-decorator API."""
    decorator = sio.on(name)
    assert decorator is not None
    return decorator


@dataclass
class _ConnectionAccess:
    """Authenticated identity and server-authorized subscriptions for one SID."""

    id: uuid.UUID
    role: Role
    rooms: set[str] = field(default_factory=set)
    presence_entities: set[tuple[str, str]] = field(default_factory=set)
    typing_entities: set[tuple[str, str]] = field(default_factory=set)


_connection_access: dict[str, _ConnectionAccess] = {}


def _bearer_from_headers(headers) -> str | None:
    """Pull a Bearer token from raw ASGI headers (list of (bytes, bytes))."""
    for key, value in headers or []:
        if key == b"authorization":
            decoded = value.decode("latin-1")
            if decoded.lower().startswith("bearer "):
                return decoded[7:].strip()
    return None


async def authenticate_socket_token(auth, headers, db):
    """Verify the Socket.IO connect credentials.

    Returns the authenticated User on success; raises ConnectionRefusedError on
    any failure so the client is rejected before joining the namespace. Mirrors
    REST's identity authenticator so verification logic cannot drift.
    """
    token = None
    if isinstance(auth, dict):
        raw = auth.get("token")
        if isinstance(raw, str):
            token = raw
    if not token:
        token = _bearer_from_headers(headers)
    if not token:
        raise ConnectionRefusedError("authentication required")
    try:
        return await build_access_token_authenticator(db).authenticate(token)
    except Exception:
        raise ConnectionRefusedError("invalid token")


@sio.event
async def connect(sid, environ, auth=None):  # type: ignore[no-untyped-def]
    """Authenticate on connect.

    The token rides in the ``auth`` handshake (socket.io-client sets it from the
    access JWT); a Bearer header is accepted as a fallback. On success the
    connection is roomed by user id.
    """
    import app.core.db as db_module

    scope = environ.get("asgi.scope") if isinstance(environ, dict) else None
    headers = scope.get("headers") if isinstance(scope, dict) else None
    async with db_module.async_session() as db:
        user = await authenticate_socket_token(auth, headers, db)
    await sio.save_session(sid, {"user_id": str(user.id), "role": user.role.value})
    await sio.enter_room(sid, f"user:{user.id}")
    _connection_access[sid] = _ConnectionAccess(id=user.id, role=user.role)


def _conversation_id(value: object) -> uuid.UUID | None:
    if not isinstance(value, (str, uuid.UUID)):
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _lead_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


async def _access_for_sid(sid: str) -> _ConnectionAccess | None:
    access = _connection_access.get(sid)
    if access is not None:
        return access
    try:
        session = await sio.get_session(sid)
        if not isinstance(session, dict):
            return None
        access = _ConnectionAccess(
            id=uuid.UUID(str(session.get("user_id", ""))),
            role=Role(str(session.get("role", ""))),
        )
    except (KeyError, TypeError, ValueError):
        return None
    _connection_access[sid] = access
    return access


async def _authorize_entity(
    sid: str, entity_type: str, entity_id: uuid.UUID | int
) -> _ConnectionAccess | None:
    access = await _access_for_sid(sid)
    if access is None:
        return None

    import app.core.db as db_module

    try:
        async with db_module.async_session() as db:
            if entity_type == "conv" and isinstance(entity_id, uuid.UUID):
                allowed = await viewer_can_access_conversation(db, entity_id, access)
            elif (
                entity_type == "lead"
                and isinstance(entity_id, int)
                and _lead_id(entity_id) is not None
            ):
                allowed = await viewer_can_access_lead(db, entity_id, access)
            else:
                return None
    except Exception as exc:  # noqa: BLE001 - authorization errors fail closed
        logger.warning(
            "realtime authorization check failed entity_type=%s error_type=%s",
            entity_type,
            type(exc).__name__,
        )
        return None
    if not allowed:
        logger.info("realtime subscription denied entity_type=%s", entity_type)
        return None
    return access


def _presence_entity(data: object, *, default_type: str) -> tuple[str, uuid.UUID | int, str] | None:
    if not isinstance(data, dict):
        return None
    entity_type = data.get("entity_type", default_type)
    raw_id = data.get("entity_id")
    if entity_type == "conv":
        entity_id = _conversation_id(raw_id)
    elif entity_type == "lead":
        entity_id = _lead_id(raw_id)
    else:
        return None
    if entity_id is None:
        return None
    return entity_type, entity_id, str(entity_id)


@_socket_event("join conversation")
async def _join_conversation(sid, data):  # type: ignore[no-untyped-def]
    """Client opens a conversation: join its room so emits target only it.

    Idempotent — re-joining an already-joined room is a no-op.
    """
    conv_id = _conversation_id(data.get("conversation_id") if isinstance(data, dict) else None)
    if conv_id is None:
        return
    access = await _authorize_entity(sid, "conv", conv_id)
    if access is None:
        return
    room = f"conv:{conv_id}"
    await sio.enter_room(sid, room)
    access.rooms.add(room)


@_socket_event("leave conversation")
async def _leave_conversation(sid, data):  # type: ignore[no-untyped-def]
    conv_id = _conversation_id(data.get("conversation_id") if isinstance(data, dict) else None)
    access = await _access_for_sid(sid)
    if conv_id is None or access is None:
        return
    room = f"conv:{conv_id}"
    if room not in access.rooms:
        return
    await sio.leave_room(sid, room)
    access.rooms.discard(room)


@_socket_event("join lead")
async def _join_lead(sid, data):  # type: ignore[no-untyped-def]
    """Client opens a lead detail: join its room so lead.updated events target it."""
    lead_id = _lead_id(data.get("lead_id") if isinstance(data, dict) else None)
    if lead_id is None:
        return
    access = await _authorize_entity(sid, "lead", lead_id)
    if access is None:
        return
    room = f"lead:{lead_id}"
    await sio.enter_room(sid, room)
    access.rooms.add(room)


@_socket_event("leave lead")
async def _leave_lead(sid, data):  # type: ignore[no-untyped-def]
    lead_id = _lead_id(data.get("lead_id") if isinstance(data, dict) else None)
    access = await _access_for_sid(sid)
    if lead_id is None or access is None:
        return
    room = f"lead:{lead_id}"
    if room not in access.rooms:
        return
    await sio.leave_room(sid, room)
    access.rooms.discard(room)


# --- presence events (viewing / typing) ---


@_socket_event("presence join")
async def _presence_join(sid, data):  # type: ignore[no-untyped-def]
    """Client enters a lead/conversation view: register presence."""
    from app.services.presence import join_viewing

    entity = _presence_entity(data, default_type="lead")
    if entity is None:
        return
    entity_type, entity_id, canonical_id = entity
    access = await _authorize_entity(sid, entity_type, entity_id)
    if access is None:
        return
    await join_viewing(entity_type, entity_id, str(access.id))
    access.presence_entities.add((entity_type, canonical_id))


@_socket_event("presence leave")
async def _presence_leave(sid, data):  # type: ignore[no-untyped-def]
    """Client leaves a lead/conversation view: clear presence."""
    from app.services.presence import leave_viewing

    entity = _presence_entity(data, default_type="lead")
    access = await _access_for_sid(sid)
    if entity is None or access is None:
        return
    entity_type, entity_id, canonical_id = entity
    key = (entity_type, canonical_id)
    if key not in access.presence_entities:
        return
    await leave_viewing(entity_type, entity_id, str(access.id))
    access.presence_entities.discard(key)


@_socket_event("presence heartbeat")
async def _presence_heartbeat(sid, data):  # type: ignore[no-untyped-def]
    """Periodic heartbeat to keep presence alive."""
    from app.services.presence import heartbeat_viewing

    entity = _presence_entity(data, default_type="lead")
    if entity is None:
        return
    entity_type, entity_id, canonical_id = entity
    access = await _authorize_entity(sid, entity_type, entity_id)
    if access is None:
        return
    await heartbeat_viewing(entity_type, entity_id, str(access.id))
    access.presence_entities.add((entity_type, canonical_id))


@_socket_event("presence typing")
async def _presence_typing(sid, data):  # type: ignore[no-untyped-def]
    """Client is typing in a conversation."""
    from app.services.presence import start_typing

    entity = _presence_entity(data, default_type="conv")
    if entity is None:
        return
    entity_type, entity_id, canonical_id = entity
    access = await _authorize_entity(sid, entity_type, entity_id)
    if access is None:
        return
    await start_typing(entity_type, canonical_id, str(access.id))
    access.typing_entities.add((entity_type, canonical_id))


@_socket_event("presence stop typing")
async def _presence_stop_typing(sid, data):  # type: ignore[no-untyped-def]
    """Client stopped typing."""
    from app.services.presence import stop_typing

    entity = _presence_entity(data, default_type="conv")
    access = await _access_for_sid(sid)
    if entity is None or access is None:
        return
    entity_type, entity_id, canonical_id = entity
    key = (entity_type, canonical_id)
    if key not in access.typing_entities:
        return
    access = await _authorize_entity(sid, entity_type, entity_id)
    if access is None:
        return
    await stop_typing(entity_type, canonical_id, str(access.id))
    access.typing_entities.discard(key)


@sio.event
async def disconnect(sid, reason=None):  # type: ignore[no-untyped-def]
    """Best-effort cleanup for presence created by this authenticated SID."""
    del reason
    access = _connection_access.pop(sid, None)
    if access is None:
        return

    from app.services.presence import leave_viewing, stop_typing

    for entity_type, entity_id in tuple(access.presence_entities):
        try:
            parsed_id: uuid.UUID | int = (
                uuid.UUID(entity_id) if entity_type == "conv" else int(entity_id)
            )
            await leave_viewing(entity_type, parsed_id, str(access.id))
        except Exception as exc:  # noqa: BLE001 - disconnect cleanup is best effort
            logger.warning(
                "realtime presence cleanup failed entity_type=%s error_type=%s",
                entity_type,
                type(exc).__name__,
            )
    for entity_type, entity_id in tuple(access.typing_entities):
        try:
            await stop_typing(entity_type, entity_id, str(access.id))
        except Exception as exc:  # noqa: BLE001 - disconnect cleanup is best effort
            logger.warning(
                "realtime typing cleanup failed entity_type=%s error_type=%s",
                entity_type,
                type(exc).__name__,
            )
