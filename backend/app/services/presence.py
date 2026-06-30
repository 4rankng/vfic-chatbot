"""Redis-backed collaborative presence.

Tracks which recruiters are viewing/typing on which leads and conversations.
Uses Redis SET keys with TTL so stale presence auto-expires. Presence changes
are broadcast via Socket.IO rooms.

Key patterns:
  ``vfic:presence:lead:{lead_id}``  — SET of user_ids viewing that lead
  ``vfic:presence:conv:{conv_id}`` — SET of user_ids viewing that conversation
  ``vfic:presence:typing:{conv_id}:{user_id}`` — TTL key for typing indicator

All keys auto-expire after ``VIEWER_TTL`` seconds of inactivity (heartbeat
required to stay alive). Typing keys expire after ``TYPING_TTL`` seconds.
"""
from __future__ import annotations

import json
import logging

from app.core.redis import get_redis
from app.realtime.emitter import emit_event

logger = logging.getLogger(__name__)

VIEWER_TTL = 30  # seconds — must heartbeat within this window
TYPING_TTL = 4  # seconds — typing indicator auto-clears


def _viewer_key(entity_type: str, entity_id) -> str:
    return f"vfic:presence:{entity_type}:{entity_id}"


def _typing_key(entity_type: str, entity_id: str, user_id: str) -> str:
    return f"vfic:presence:typing:{entity_type}:{entity_id}:{user_id}"


async def join_viewing(entity_type: str, entity_id, user_id: str, user_name: str | None = None) -> dict:
    """Register a user as viewing an entity. Returns current viewers."""
    redis = get_redis()
    key = _viewer_key(entity_type, entity_id)
    await redis.sadd(key, json.dumps({"user_id": user_id, "name": user_name}))
    await redis.expire(key, VIEWER_TTL)
    viewers = await _get_viewers(redis, key)
    room = f"{entity_type}:{entity_id}"
    await emit_event(
        "presence.viewers",
        {"entity_type": entity_type, "entity_id": str(entity_id), "viewers": viewers},
        room=room,
    )
    return viewers


async def leave_viewing(entity_type: str, entity_id, user_id: str) -> dict:
    """Remove a user from an entity's viewer set. Returns remaining viewers."""
    redis = get_redis()
    key = _viewer_key(entity_type, entity_id)
    # Remove all entries with matching user_id (stored as JSON)
    members = await redis.smembers(key)
    for member in members:
        data = json.loads(member)
        if data.get("user_id") == user_id:
            await redis.srem(key, member)
    viewers = await _get_viewers(redis, key)
    room = f"{entity_type}:{entity_id}"
    await emit_event(
        "presence.viewers",
        {"entity_type": entity_type, "entity_id": str(entity_id), "viewers": viewers},
        room=room,
    )
    return viewers


async def heartbeat_viewing(entity_type: str, entity_id, user_id: str, user_name: str | None = None) -> dict:
    """Refresh the TTL for a viewer (called periodically while viewing)."""
    redis = get_redis()
    key = _viewer_key(entity_type, entity_id)
    # Re-add with current name (in case it changed)
    member = json.dumps({"user_id": user_id, "name": user_name})
    await redis.sadd(key, member)
    await redis.expire(key, VIEWER_TTL)
    return await _get_viewers(redis, key)


async def start_typing(entity_type: str, entity_id: str, user_id: str, user_name: str | None = None) -> None:
    """Signal that a user is typing. Auto-expires after TYPING_TTL."""
    redis = get_redis()
    key = _typing_key(entity_type, entity_id, user_id)
    await redis.set(key, user_name or "", ex=TYPING_TTL)
    room = f"{entity_type}:{entity_id}"
    await emit_event(
        "presence.typing",
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_id": user_id,
            "user_name": user_name,
        },
        room=room,
    )


async def stop_typing(entity_type: str, entity_id: str, user_id: str) -> None:
    """Explicitly clear a typing indicator."""
    redis = get_redis()
    key = _typing_key(entity_type, entity_id, user_id)
    await redis.delete(key)
    room = f"{entity_type}:{entity_id}"
    await emit_event(
        "presence.typing",
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_id": user_id,
            "user_name": None,
        },
        room=room,
    )


async def get_viewers(entity_type: str, entity_id) -> list[dict]:
    """Return current viewers for an entity (no broadcast)."""
    redis = get_redis()
    key = _viewer_key(entity_type, entity_id)
    return await _get_viewers(redis, key)


async def get_typing_users(entity_type: str, entity_id: str) -> list[dict]:
    """Return users currently typing on an entity (scan pattern)."""
    redis = get_redis()
    pattern = f"vfic:presence:typing:{entity_type}:{entity_id}:*"
    typing_users = []
    async for key in redis.scan_iter(match=pattern):
        name = await redis.get(key)
        # Extract user_id from key pattern
        parts = key.decode() if isinstance(key, bytes) else key
        user_id = parts.split(":")[-1]
        typing_users.append({"user_id": user_id, "user_name": name.decode() if isinstance(name, bytes) else name})
    return typing_users


async def _get_viewers(redis, key: str) -> list[dict]:
    """Parse viewer SET members into a list of dicts."""
    members = await redis.smembers(key)
    viewers = []
    for member in members:
        try:
            viewers.append(json.loads(member))
        except (json.JSONDecodeError, TypeError):
            pass
    return viewers
