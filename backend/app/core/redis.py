"""Redis clients: async (app realtime pub/sub + cache) and sync (RQ).

RQ requires a blocking redis client; the app uses the async one for SSE fan-out
and the per-chat mutex fallback.
"""
import redis
import redis.asyncio as aioredis

from app.core.config import get_settings

_settings = get_settings()

_async: aioredis.Redis | None = None
_sync: redis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Lazily-built singleton async redis client."""
    global _async
    if _async is None:
        _async = aioredis.from_url(_settings.redis_url, decode_responses=True)
    return _async


def get_redis_sync() -> redis.Redis:
    """Lazily-built singleton SYNC redis client (for RQ workers)."""
    global _sync
    if _sync is None:
        _sync = redis.from_url(_settings.redis_url, decode_responses=True)
    return _sync

