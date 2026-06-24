"""Best-effort realtime fan-out over Redis pub/sub.

Publishing is fire-and-forget: a Redis outage must never block core conversation
flow. The SSE endpoint (app/api/realtime.py) subscribes to the same channel.
"""
import json
import logging

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

CHANNEL = "vfic:events"


async def publish_event(event_type: str, payload: dict) -> None:
    """Publish ``{type, payload}`` to the realtime channel. Swallows errors."""
    try:
        await get_redis().publish(CHANNEL, json.dumps({"type": event_type, "payload": payload}))
    except Exception as exc:  # noqa: BLE001 — realtime must not break writes
        logger.warning("realtime publish failed: %s", exc)
