"""Redis clients: async (app realtime pub/sub + cache) and sync (RQ).

RQ requires a blocking redis client; the app uses the async one for SSE fan-out
and the per-chat mutex fallback.
"""

from typing import Awaitable, TypeVar, cast

import redis
import redis.asyncio as aioredis

from app.core.config import get_settings

_settings = get_settings()

_async: aioredis.Redis | None = None
_sync: redis.Redis | None = None

_SyncResult = TypeVar("_SyncResult")


def sync_value(result: _SyncResult | Awaitable[_SyncResult]) -> _SyncResult:
    """The concrete result of a command on the SYNC client.

    redis-py 7 declares one command surface for both clients, so every command
    is annotated ``Awaitable[T] | T`` even on ``redis.Redis``, where the value is
    always already resolved. This unwraps that union once, at the call, instead
    of leaving every downstream read of the result untyped — which is what made
    comparisons, arithmetic and ``int(...)`` on a Redis reply look unsupported.

    Only ever pass a call made on :func:`get_redis_sync`; on an awaitable this
    would hand back the coroutine instead of its result.
    """
    return cast(_SyncResult, result)


def async_value(result: _SyncResult | Awaitable[_SyncResult]) -> Awaitable[_SyncResult]:
    """The awaitable arm of a command on the ASYNC client.

    The mirror of :func:`sync_value`: the same shared declaration makes an
    ``aioredis`` command ``Awaitable[T] | T``, so ``await`` on it is rejected for
    the arm that is not awaitable. Only ever pass a call made on
    :func:`get_redis`.
    """
    return cast("Awaitable[_SyncResult]", result)


def get_redis() -> aioredis.Redis:
    """Lazily-built singleton async redis client."""
    global _async
    if _async is None:
        _async = aioredis.from_url(_settings.redis_url, decode_responses=True)
    return _async


def get_redis_sync() -> redis.Redis:
    """Lazily-built singleton SYNC redis client.

    Keep responses as bytes here. RQ stores pickled job payloads in Redis, and
    redis-py with ``decode_responses=True`` tries to UTF-8 decode those binary
    values before RQ can unpickle them.
    """
    global _sync
    if _sync is None:
        _sync = redis.from_url(_settings.redis_url, decode_responses=False)
    return _sync
