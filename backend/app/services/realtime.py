"""Best-effort realtime fan-out over Socket.IO.

Publishing is fire-and-forget: a Socket.IO failure must never block core
conversation flow. The Socket.IO AsyncServer (``app/realtime/socketio.py``) fans
events out to per-conversation rooms via the Socket.IO Redis bus. The legacy SSE
pub/sub channel (``vfic:events``) was removed when the Socket.IO cutover
completed — it carried zero subscribers and cost one Redis ``PUBLISH`` per event
on the realtime hot path.
"""

import logging

logger = logging.getLogger(__name__)


async def publish_event(event_type: str, payload: dict) -> None:
    """Publish ``{type, payload}`` to the Socket.IO bus. Swallows errors.

    Socket.IO targets the conversation room derived from the payload so only
    subscribed clients receive it.
    """
    try:
        # Imported lazily so services.realtime stays import-light and never
        # triggers the AsyncServer construction at import time.
        from app.realtime.emitter import emit_event
        from app.realtime.socketio import _room_for_payload

        await emit_event(event_type, payload, room=_room_for_payload(payload))
    except Exception as exc:  # noqa: BLE001 — realtime must not break writes
        logger.warning("socket.io publish failed: %s", exc)
