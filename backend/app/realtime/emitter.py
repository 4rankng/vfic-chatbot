"""Write-only Socket.IO emit bridge for publishing processes.

The chat turn persists messages in the RQ worker-chatbot (and recruiter actions
in the web process); both call ``services.realtime.publish_event``. This module
publishes onto the same Socket.IO Redis bus the AsyncServer
(``app.realtime.socketio.sio``) subscribes to, so emits from ANY process reach
every connected browser socket. ``write_only=True`` means NO local server is
needed here — it only publishes.
"""

from __future__ import annotations

import logging

import socketio

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Lazily built; rebuilt after any failure so a connection bound to a previous
# event loop (the RQ worker asyncio.run's each job; tests run one loop per test)
# never poisons subsequent emits.
_manager: socketio.AsyncRedisManager | None = None


def _get_manager() -> socketio.AsyncRedisManager:
    global _manager
    if _manager is None:
        _manager = socketio.AsyncRedisManager(settings.redis_url, write_only=True)
    return _manager


def reset_manager() -> None:
    """Drop the cached manager (the next emit rebuilds it). Called on failure
    and from tests that need a clean connection."""
    global _manager
    _manager = None


async def emit_event(event_type: str, payload: dict, room: str | None = None) -> None:
    """Best-effort emit. Realtime must never break a write, so every error is
    swallowed; on failure the manager is reset so the next emit gets a fresh
    connection instead of reusing a stale, loop-bound one."""
    try:
        await _get_manager().emit(event_type, payload, room=room)
    except Exception as exc:  # noqa: BLE001 — realtime must not break writes
        logger.warning("socket.io emit failed (%s): %s", event_type, exc)
        reset_manager()
