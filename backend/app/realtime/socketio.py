"""Socket.IO realtime server (replaces the SSE firehose for chat).

A single AsyncServer fronts the web process. It is mounted at the ASGI root
(``socketio.ASGIApp`` with ``other_asgi_app=fastapi``) so Socket.IO traffic on
``/socket.io/`` is served alongside the REST API. The server uses an
``AsyncRedisManager`` so emits published by OTHER processes (the RQ
worker-chatbot, which records bot outcomes) over the same Redis bus are fanned
out to the browser sockets held by THIS process.

Auth: the browser connects with ``{ auth: { token } }``; the connect handler
verifies the access JWT via the same ``get_user_from_token`` used by REST,
refuses on failure, and rooms the connection by user and (on demand) by
conversation. This replaces the SSE ``?token=`` workaround.
"""

from __future__ import annotations

import logging

import socketio
from socketio.exceptions import ConnectionRefusedError

from app.api.dependencies import get_user_from_token
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _room_for_payload(payload: dict) -> str | None:
    """The Socket.IO room a realtime event targets.

    Conversation events carry ``conversation_id`` or ``id`` → ``conv:{id}``.
    Lead events carry ``lead_id`` → ``lead:{id}``.
    Events with neither are broadcast to all connected clients (room=None).
    """
    if payload.get("lead_id") is not None:
        return f"lead:{payload['lead_id']}"
    cid = payload.get("conversation_id") or payload.get("id")
    if not cid:
        return None
    return f"conv:{cid}"


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
    REST's ``get_user_from_token`` so verification logic cannot drift.
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
        return await get_user_from_token(token, db)
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


@sio.on("join conversation")
async def _join_conversation(sid, data):  # type: ignore[no-untyped-def]
    """Client opens a conversation: join its room so emits target only it.

    Idempotent — re-joining an already-joined room is a no-op.
    """
    conv_id = data.get("conversation_id") if isinstance(data, dict) else None
    if not conv_id:
        return
    await sio.enter_room(sid, f"conv:{conv_id}")


@sio.on("leave conversation")
async def _leave_conversation(sid, data):  # type: ignore[no-untyped-def]
    conv_id = data.get("conversation_id") if isinstance(data, dict) else None
    if not conv_id:
        return
    await sio.leave_room(sid, f"conv:{conv_id}")


@sio.on("join lead")
async def _join_lead(sid, data):  # type: ignore[no-untyped-def]
    """Client opens a lead detail: join its room so lead.updated events target it."""
    lead_id = data.get("lead_id") if isinstance(data, dict) else None
    if not lead_id:
        return
    await sio.enter_room(sid, f"lead:{lead_id}")


@sio.on("leave lead")
async def _leave_lead(sid, data):  # type: ignore[no-untyped-def]
    lead_id = data.get("lead_id") if isinstance(data, dict) else None
    if not lead_id:
        return
    await sio.leave_room(sid, f"lead:{lead_id}")


# --- presence events (viewing / typing) ---


@sio.on("presence join")
async def _presence_join(sid, data):  # type: ignore[no-untyped-def]
    """Client enters a lead/conversation view: register presence."""
    from app.services.presence import join_viewing

    session = await sio.get_session(sid)
    user_id = session.get("user_id", "") if session else ""
    entity_type = data.get("entity_type", "lead") if isinstance(data, dict) else "lead"
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    if not entity_id:
        return
    await join_viewing(entity_type, entity_id, user_id)


@sio.on("presence leave")
async def _presence_leave(sid, data):  # type: ignore[no-untyped-def]
    """Client leaves a lead/conversation view: clear presence."""
    from app.services.presence import leave_viewing

    session = await sio.get_session(sid)
    user_id = session.get("user_id", "") if session else ""
    entity_type = data.get("entity_type", "lead") if isinstance(data, dict) else "lead"
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    if not entity_id:
        return
    await leave_viewing(entity_type, entity_id, user_id)


@sio.on("presence heartbeat")
async def _presence_heartbeat(sid, data):  # type: ignore[no-untyped-def]
    """Periodic heartbeat to keep presence alive."""
    from app.services.presence import heartbeat_viewing

    session = await sio.get_session(sid)
    user_id = session.get("user_id", "") if session else ""
    entity_type = data.get("entity_type", "lead") if isinstance(data, dict) else "lead"
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    if not entity_id:
        return
    await heartbeat_viewing(entity_type, entity_id, user_id)


@sio.on("presence typing")
async def _presence_typing(sid, data):  # type: ignore[no-untyped-def]
    """Client is typing in a conversation."""
    from app.services.presence import start_typing

    session = await sio.get_session(sid)
    user_id = session.get("user_id", "") if session else ""
    entity_type = data.get("entity_type", "conv") if isinstance(data, dict) else "conv"
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    if not entity_id:
        return
    await start_typing(entity_type, str(entity_id), user_id)


@sio.on("presence stop typing")
async def _presence_stop_typing(sid, data):  # type: ignore[no-untyped-def]
    """Client stopped typing."""
    from app.services.presence import stop_typing

    session = await sio.get_session(sid)
    user_id = session.get("user_id", "") if session else ""
    entity_type = data.get("entity_type", "conv") if isinstance(data, dict) else "conv"
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    if not entity_id:
        return
    await stop_typing(entity_type, str(entity_id), user_id)
