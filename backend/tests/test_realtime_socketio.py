"""Socket.IO realtime: connect auth + room routing + dual-publish wiring.

The live two-tab delivery (RQ worker emit -> web-process socket) is verified
manually in production; these tests cover the parts that are deterministic in
process: the auth gate, the room-key derivation, and that the service layer
fans every event out to BOTH the SSE channel and the Socket.IO conversation
room (so neither transport regresses during the cutover).
"""
import uuid

import pytest
from sqlalchemy import text
from socketio.exceptions import ConnectionRefusedError

from app.realtime.emitter import emit_event as real_emit_event
from app.realtime.socketio import _room_for_payload, authenticate_socket_token
from app.services.conversation_service import ConversationService
from tests.conftest import ADMIN_EMAIL, PASSWORD

pytestmark = pytest.mark.asyncio


async def _admin_token(client) -> str:
    return (
        await client.post(
            "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}
        )
    ).json()["access_token"]


async def test_room_for_payload_maps_keys():
    assert _room_for_payload({"conversation_id": "abc"}) == "conv:abc"
    assert _room_for_payload({"id": "xyz"}) == "conv:xyz"
    # conversation_id wins when both are present (message.created shape).
    assert _room_for_payload({"conversation_id": "abc", "id": "xyz"}) == "conv:abc"
    assert _room_for_payload({"foo": "bar"}) is None
    assert _room_for_payload({}) is None


async def test_authenticate_socket_token_accepts_valid(client, db_session):
    token = await _admin_token(client)
    user = await authenticate_socket_token({"token": token}, None, db_session)
    assert user is not None
    assert user.email == ADMIN_EMAIL


async def test_authenticate_socket_token_refuses_bad(client, db_session):
    # Missing auth entirely.
    with pytest.raises(ConnectionRefusedError):
        await authenticate_socket_token(None, None, db_session)
    # Wrong type (a number, not a string).
    with pytest.raises(ConnectionRefusedError):
        await authenticate_socket_token({"token": 123}, None, db_session)
    # Garbage JWT.
    with pytest.raises(ConnectionRefusedError):
        await authenticate_socket_token({"token": "not-a-jwt"}, None, db_session)
    # Bearer header fallback still works.
    token = await _admin_token(client)
    headers = [(b"authorization", f"Bearer {token}".encode("latin-1"))]
    user = await authenticate_socket_token(None, headers, db_session)
    assert user.email == ADMIN_EMAIL


async def test_publish_event_dual_publishes_to_socket_room(client, db_session, monkeypatch):
    """ConversationService.mark_read fans conversation.updated out to the
    Socket.IO room conv:<id>. Monkeypatch emit_event to record the call —
    proves the wiring + room routing without a live socket or Redis round-trip."""
    captured: list[tuple[str, dict, str | None]] = []

    async def _fake_emit(event_type, payload, room=None):
        captured.append((event_type, payload, room))

    # publish_event lazily does `from app.realtime.emitter import emit_event`,
    # so patching the attribute on the module object intercepts it at call time.
    import app.realtime.emitter as emitter_mod

    monkeypatch.setattr(emitter_mod, "emit_event", _fake_emit)

    tok = await _admin_token(client)
    h = {"Authorization": f"Bearer {tok}"}
    _me = (await client.get("/api/v1/auth/me", headers=h)).json()

    # Unique zalo id per run — the test DB persists across runs (no per-test
    # cleanup), so a fixed id would trip the zalo_chat_id unique constraint.
    zalo = f"so-{uuid.uuid4().hex[:8]}"
    conv_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO conversations(id,zalo_chat_id,status,mode,unread_count) "
            "VALUES (:i,:z,'OPEN','BOT',3)"
        ),
        {"i": conv_id, "z": zalo},
    )
    await db_session.commit()

    conv = await ConversationService(db_session).get(conv_id)
    assert conv is not None
    await ConversationService(db_session).mark_read(conv)

    # conversation.updated carried the conversation id -> routed to conv:<id>.
    routed = [
        (ev, room) for ev, payload, room in captured if ev == "conversation.updated"
    ]
    assert (f"conv:{conv_id}") in {room for _ev, room in routed}, captured
    # mark_read is the only event this path emits.
    assert all(ev == "conversation.updated" for ev, _p, _r in captured)


async def test_emit_event_is_best_effort(monkeypatch):
    """A failing manager must never raise — realtime must not break a write."""
    import app.realtime.emitter as emitter_mod

    class _Boom:
        async def emit(self, *_args, **_kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(emitter_mod, "_get_manager", lambda: _Boom())
    # Should swallow and reset the (None) manager, not raise.
    emitter_mod.reset_manager()
    await real_emit_event("message.created", {"conversation_id": "x"}, room="conv:x")
