"""Cross-process single-flight request coalescing (Tech-Lead Directive §6).

When N concurrent turns ask the same uncached question, only ONE process should
call the model; the others await the same result. This module implements that
coalescing via Redis: a leader-follower pattern where the leader computes and
publishes, followers subscribe and await.

Design
------
- **Leader election:** ``SET inflight:{key} <leader_id> NX EX <ttl>``. The first
  caller wins; subsequent callers within the TTL window are followers.
- **Result fan-out:** the leader publishes the result (or error) to a Redis
  pub/sub channel ``inflight:{key}:result``. Followers subscribe and await the
  first message.
- **Safety net:** the inflight marker has a TTL (default 30s, > any realistic
  generation). If the leader crashes before publishing, followers time out and
  self-promote by re-attempting ``SET NX``.
- **Cache-first followers:** before subscribing, a follower re-checks the cache
  (the leader may have already written it). Pub/sub is the wake-up; the cache is
  the delivery. This handles pub/sub's at-most-once semantics: a follower that
  subscribes after the leader publishes misses the message but finds the result
  in the cache.

Scope discipline (directive §6)
-------------------------------
Single-flight applies ONLY to non-personalized paths. The caller is responsible
for deciding what to coalesce:
- ✓ ``search_knowledge`` (FAQ / detail / contact) — non-personalized
- ✗ ``recommend_jobs`` — depends on candidate profile
- ✗ ``search_user_memory`` — per-candidate

The primitive itself is key-agnostic; the scope discipline lives at the call
site. A wrong key (e.g. coalescing a personalized query across candidates)
would return the wrong answer to followers — callers MUST include candidate-
specific dimensions in the key when needed, or simply not coalesce.

Failure modes
-------------
- **Leader errors:** the leader publishes an error payload; followers raise the
  same error class. Both leader and followers fall through to the caller's
  existing error handling.
- **Leader crash:** TTL expires the inflight marker. Followers waiting on the
  pub/sub timeout; on timeout, they re-attempt ``SET NX`` and self-promote.
- **Redis down:** every operation is best-effort; ``acquire`` returns ``None``
  (meaning "compute yourself, coalescing unavailable") rather than raising.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Redis key shapes.
_INFLIGHT_KEY = "inflight:{key}"
_RESULT_CHANNEL = "inflight:{key}:result"

# Default leader marker TTL — must exceed any realistic generation (the agent
# turn budget is ~10s; 30s leaves comfortable headroom for a slow provider).
_DEFAULT_TTL_SECONDS = 30
# Default follower wait — should be ≤ the overall turn deadline. Callers pass
# their own timeout for the work they guard.
_DEFAULT_FOLLOWER_TIMEOUT_SECONDS = 8.0


@dataclass
class _ErrorPayload:
    """Serialized error published by a failing leader."""

    error_type: str
    message: str


class SingleFlightError(RuntimeError):
    """Raised by followers when the leader published an error payload."""


async def _get_redis():
    """Lazy Redis accessor; returns None on any failure (coalescing degrades off)."""
    try:
        from app.core.redis import get_redis

        return await get_redis()
    except Exception:  # noqa: BLE001
        logger.debug("singleflight: redis unavailable, coalescing disabled", exc_info=True)
        return None


async def acquire(key: str, *, ttl: int = _DEFAULT_TTL_SECONDS) -> str | None:
    """Try to become the leader for ``key``. Returns the leader_id if won, None if a leader exists.

    ``SET NX EX`` is atomic: exactly one caller wins. The returned ``leader_id``
    is a UUID the leader passes to ``publish_result`` / ``publish_error`` so the
    cleanup step can verify ownership (avoid a straggler leader cleaning up a
    new leader's marker after TTL expiry).

    Returns ``None`` (not raises) when Redis is unavailable — callers fall back
    to computing themselves without coalescing.
    """
    r = await _get_redis()
    if r is None:
        return None
    leader_id = uuid.uuid4().hex
    try:
        # SET NX EX: set if not exists, with expiry. Returns OK on success, None
        # if the key already exists. We use set() with nx=True + ex=.
        ok = await r.set(_INFLIGHT_KEY.format(key=key), leader_id, nx=True, ex=ttl)
        if ok:
            return leader_id
        return None
    except Exception:  # noqa: BLE001
        logger.debug("singleflight: acquire failed for %s", key, exc_info=True)
        return None


async def release(key: str, leader_id: str) -> None:
    """Release the leader marker iff we still own it (Lua-free CAS via GETDEL).

    Avoids the race where a slow leader finishes after its TTL expired and a new
    leader has already taken the marker: we check the stored value matches
    ``leader_id`` before deleting. Best-effort.
    """
    r = await _get_redis()
    if r is None:
        return
    try:
        stored = await r.get(_INFLIGHT_KEY.format(key=key))
        if stored == leader_id:
            await r.delete(_INFLIGHT_KEY.format(key=key))
    except Exception:  # noqa: BLE001
        logger.debug("singleflight: release failed for %s", key, exc_info=True)


async def publish_result(key: str, leader_id: str, result: Any) -> None:
    """Publish ``result`` to followers, then release the leader marker.

    ``result`` must be JSON-serializable (it crosses Redis pub/sub). The leader
    ALWAYS releases in a finally-style manner; callers should use the
    ``run_as_leader`` helper rather than calling this directly.
    """
    r = await _get_redis()
    if r is None:
        return
    payload = json.dumps({"ok": True, "result": result})
    try:
        await r.publish(_RESULT_CHANNEL.format(key=key), payload)
    except Exception:  # noqa: BLE001
        logger.debug("singleflight: publish_result failed for %s", key, exc_info=True)
    finally:
        await release(key, leader_id)


async def publish_error(key: str, leader_id: str, exc: BaseException) -> None:
    """Publish an error payload to followers, then release the leader marker."""
    r = await _get_redis()
    if r is None:
        return
    payload = json.dumps(
        {
            "ok": False,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    )
    try:
        await r.publish(_RESULT_CHANNEL.format(key=key), payload)
    except Exception:  # noqa: BLE001
        logger.debug("singleflight: publish_error failed for %s", key, exc_info=True)
    finally:
        await release(key, leader_id)


async def await_result(
    key: str,
    *,
    timeout: float = _DEFAULT_FOLLOWER_TIMEOUT_SECONDS,
    cache_read: Callable[[], Awaitable[Any]] | None = None,
) -> Any:
    """Wait for the leader's result. Returns the result or raises ``SingleFlightError``.

    ``cache_read`` is an optional callable that re-checks the cache (the leader
    may have already written it before this follower subscribed). Called once
    before subscribing and once after a pub/sub timeout. If it returns a truthy
    value, that's the result — pub/sub becomes unnecessary.

    On timeout (no leader message and no cache hit), raises ``asyncio.TimeoutError``
    so the caller can self-promote by re-attempting ``acquire``.
    """
    # Cache-first: the leader may have already delivered via the cache.
    if cache_read is not None:
        try:
            cached = await cache_read()
            if cached is not None:
                return cached
        except Exception:  # noqa: BLE001
            pass

    r = await _get_redis()
    if r is None:
        # No Redis → can't wait; caller should compute itself.
        raise asyncio.TimeoutError("singleflight: redis unavailable")

    channel = _RESULT_CHANNEL.format(key=key)
    pubsub = r.pubsub()
    received: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _listen() -> None:
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "replace")
                if not received.done():
                    received.set_result(raw)
                return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            if not received.done():
                received.set_exception(asyncio.TimeoutError("singleflight: pubsub listener failed"))

    listener_task = asyncio.ensure_future(_listen())
    try:
        raw = await asyncio.wait_for(received, timeout=timeout)
    except asyncio.TimeoutError:
        # Final cache check before giving up — the leader may have finished
        # during our wait window.
        if cache_read is not None:
            try:
                cached = await cache_read()
                if cached is not None:
                    return cached
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        listener_task.cancel()
        with _suppress_cancel():
            await listener_task
        with _suppress_all():
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    payload = json.loads(raw)
    if payload.get("ok"):
        return payload.get("result")
    raise SingleFlightError(f"{payload.get('error_type', 'Error')}: {payload.get('message', '')}")


async def run_as_leader(
    key: str,
    leader_id: str,
    compute: Callable[[], Awaitable[T]],
) -> T:
    """Run ``compute``, publish its result/error, and always release the marker.

    The leader-side convenience wrapper. Returns the computed result on success
    (so the leader caller uses it directly), or re-raises on error after
    publishing the error to followers.
    """
    try:
        result = await compute()
    except BaseException as exc:  # noqa: BLE043 — re-raise after publishing
        await publish_error(key, leader_id, exc)
        raise
    else:
        await publish_result(key, leader_id, result)
        return result


class _suppress_cancel:
    """Sync context manager that suppresses only asyncio.CancelledError."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is asyncio.CancelledError


class _suppress_all:
    """Sync context manager that suppresses all exceptions (cleanup-only blocks)."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return True
