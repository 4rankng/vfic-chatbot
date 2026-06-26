"""Best-effort realtime fan-out over Redis pub/sub + Socket.IO.

Publishing is fire-and-forget: a Redis outage must never block core conversation
flow. The SSE endpoint (app/api/realtime.py) subscribes to the pub/sub channel;
the Socket.IO AsyncServer (app/realtime/socketio.py) fans the same events out to
per-conversation rooms via the Socket.IO Redis bus. SSE is retained during the
cutover (dual publish); removing the SSE endpoint is a documented follow-up once
Socket.IO is confirmed live in production.
"""
import json
import logging

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

CHANNEL = "vfic:events"


async def publish_event(event_type: str, payload: dict) -> None:
    """Publish ``{type, payload}`` to both realtime buses. Swallows errors.

    SSE keeps the legacy pub/sub channel; Socket.IO targets the conversation
    room derived from the payload so only subscribed clients receive it.
    """
    try:
        await get_redis().publish(
            CHANNEL, json.dumps({"type": event_type, "payload": payload})
        )
    except Exception as exc:  # noqa: BLE001 — realtime must not break writes
        logger.warning("realtime publish failed: %s", exc)
    try:
        # Imported lazily so services.realtime stays import-light and never
        # triggers the AsyncServer construction at import time.
        from app.realtime.emitter import emit_event
        from app.realtime.socketio import _room_for_payload

        await emit_event(event_type, payload, room=_room_for_payload(payload))
    except Exception as exc:  # noqa: BLE001 — realtime must not break writes
        logger.warning("socket.io publish failed: %s", exc)
