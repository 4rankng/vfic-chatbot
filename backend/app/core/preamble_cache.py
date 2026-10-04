"""Best-effort cache helpers for the chatbot's shared preamble.

The preamble is the slow-changing context assembled on every chat turn:
- integration settings (zalo/minimax/openrouter/facebook oauth) — change only
  via admin writes or token refresh
- the assembled system prompt (persona body + active-product index) — the persona
  half is a code constant now, so only project/index-card edits invalidate it,
  plus a code deploy, which the prompt-text revision covers

Secret-bearing integration settings are cached process-locally only. Redis is
used exclusively for namespace-version counters, so decrypted secrets never
leave the Python process. Each local entry is keyed by namespace + version so
admin writes invalidate via ``bump_cache_version``.

The assembled system prompt stays in Redis because it contains no credentials
and is shared across workers.

Cache failures must never affect chat turns. On any Redis-version lookup error
the loader is invoked directly and the local cache is bypassed so stale secrets
are never served as a fallback.

The TTLs below are internal tuning constants, not deployment knobs: the preamble
changes only on admin edits (which bump the version immediately), so the TTL is
just a safety net for a missed bump — not a value operators need to tune.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar, cast

from app.core.cache import cache_get_json, cache_set_json, cache_version
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Namespaces for version-bump invalidation. ``bump_cache_version(namespace)``
# on the matching write path flips these, so the next read misses and re-reads.
NS_INTEGRATION_MINIMAX = "integration_minimax"
NS_INTEGRATION_OPENROUTER = "integration_openrouter"
NS_INTEGRATION_CUSTOM_LLM = "integration_custom_llm"
NS_INTEGRATION_ZALO = "integration_zalo"
NS_INTEGRATION_FACEBOOK = "integration_facebook"
NS_INTEGRATION_JEV = "integration_jev"
NS_PREAMBLE = "preamble"

# Integration settings change only via the admin UI; 5 min is a safety net for
# a missed version bump. The system prompt (persona + active-product index)
# changes on project edits and on a code deploy that edits the persona;
# 10 min mirrors the warm-window intent.
_INTEGRATION_TTL_SECONDS = 300
_SYSTEM_PROMPT_TTL_SECONDS = 600
_LOCAL_SECRET_CACHE_MAX_ENTRIES = 16
_MONOTONIC = time.monotonic


@dataclass(slots=True)
class _LocalSecretCacheEntry:
    namespace: str
    value: Any
    expires_at: float


_LOCAL_SECRET_CACHE: OrderedDict[str, _LocalSecretCacheEntry] = OrderedDict()
_LOCAL_NAMESPACE_KEYS: dict[str, set[str]] = {}
_LOCAL_CACHE_MISS = object()


def _evict_local_cache_key(cache_key: str) -> None:
    entry = _LOCAL_SECRET_CACHE.pop(cache_key, None)
    if entry is None:
        return
    namespace_keys = _LOCAL_NAMESPACE_KEYS.get(entry.namespace)
    if not namespace_keys:
        return
    namespace_keys.discard(cache_key)
    if not namespace_keys:
        _LOCAL_NAMESPACE_KEYS.pop(entry.namespace, None)


def _prune_expired_local_entries(now: float) -> None:
    expired_keys = [
        cache_key
        for cache_key, entry in list(_LOCAL_SECRET_CACHE.items())
        if entry.expires_at <= now
    ]
    for cache_key in expired_keys:
        _evict_local_cache_key(cache_key)


def _get_local_secret(cache_key: str, *, now: float) -> object:
    entry = _LOCAL_SECRET_CACHE.get(cache_key)
    if entry is None:
        return _LOCAL_CACHE_MISS
    if entry.expires_at <= now:
        _evict_local_cache_key(cache_key)
        return _LOCAL_CACHE_MISS
    _LOCAL_SECRET_CACHE.move_to_end(cache_key)
    return entry.value


def _store_local_secret(
    cache_key: str,
    *,
    namespace: str,
    value: Any,
    ttl_seconds: int,
    now: float,
) -> None:
    if ttl_seconds <= 0:
        return
    _prune_expired_local_entries(now)
    if cache_key in _LOCAL_SECRET_CACHE:
        _evict_local_cache_key(cache_key)
    _LOCAL_SECRET_CACHE[cache_key] = _LocalSecretCacheEntry(
        namespace=namespace,
        value=value,
        expires_at=now + ttl_seconds,
    )
    _LOCAL_NAMESPACE_KEYS.setdefault(namespace, set()).add(cache_key)
    _LOCAL_SECRET_CACHE.move_to_end(cache_key)
    while len(_LOCAL_SECRET_CACHE) > _LOCAL_SECRET_CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_LOCAL_SECRET_CACHE))
        _evict_local_cache_key(oldest_key)


def evict_local_namespace(namespace: str) -> None:
    """Drop every local secret-cache entry for one namespace."""
    for cache_key in list(_LOCAL_NAMESPACE_KEYS.get(namespace, ())):
        _evict_local_cache_key(cache_key)


def _reset_local_secret_cache() -> None:
    """Test helper: clear all process-local secret cache state."""
    _LOCAL_SECRET_CACHE.clear()
    _LOCAL_NAMESPACE_KEYS.clear()


async def _read_namespace_version(namespace: str) -> str | None:
    try:
        value = await get_redis().get(f"cachever:{namespace}")
    except Exception:  # noqa: BLE001
        logger.debug("cache version read failed for namespace %s", namespace, exc_info=True)
        return None
    return str(value or "1")


async def cached_value(
    *,
    key_prefix: str,
    namespace: str,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[T]],
) -> T:
    """Return the locally cached value for ``key_prefix`` or ``await loader()``.

    The local cache key embeds the Redis-backed namespace version so a
    ``bump_cache_version(namespace)`` on the write path invalidates without an
    explicit delete. On any Redis version-read failure, the local cache is
    bypassed and ``loader`` is invoked directly so stale secrets are never
    served.
    """
    version = await _read_namespace_version(namespace)
    if version is None:
        return await loader()
    cache_key = f"{namespace}:v{version}:{key_prefix}"
    now = _MONOTONIC()
    cached = _get_local_secret(cache_key, now=now)
    if cached is not _LOCAL_CACHE_MISS:
        return cast(T, cached)

    value = await loader()
    _store_local_secret(
        cache_key,
        namespace=namespace,
        value=value,
        ttl_seconds=ttl_seconds,
        now=_MONOTONIC(),
    )
    return value


async def cached_minimax_config(loader: Callable[[], Awaitable[dict]]) -> dict:
    """Cache the minimax runtime config dict (keyed by the minimax namespace)."""
    return await cached_value(
        key_prefix="preamble:minimax",
        namespace=NS_INTEGRATION_MINIMAX,
        ttl_seconds=_INTEGRATION_TTL_SECONDS,
        loader=loader,
    )


async def cached_openrouter_config(loader: Callable[[], Awaitable[dict]]) -> dict:
    """Cache the openrouter runtime config dict (keyed by the openrouter namespace)."""
    return await cached_value(
        key_prefix="preamble:openrouter",
        namespace=NS_INTEGRATION_OPENROUTER,
        ttl_seconds=_INTEGRATION_TTL_SECONDS,
        loader=loader,
    )


async def cached_custom_llm_config(loader: Callable[[], Awaitable[dict]]) -> dict:
    """Cache the quota-failover provider config (keyed by its own namespace)."""
    return await cached_value(
        key_prefix="preamble:fallback_llm",
        namespace=NS_INTEGRATION_CUSTOM_LLM,
        ttl_seconds=_INTEGRATION_TTL_SECONDS,
        loader=loader,
    )


async def cached_zalo_config(
    loader: Callable[[], Awaitable[dict]], *, account_key: str | None = None
) -> dict:
    """Cache the zalo runtime config dict (keyed by the zalo namespace).

    ``account_key`` gives each OA account its own entry inside the same
    namespace, so a credential write for one OA invalidates every account's
    cache through the shared version bump.
    """
    return await cached_value(
        key_prefix="preamble:zalo" if not account_key else f"preamble:zalo:{account_key}",
        namespace=NS_INTEGRATION_ZALO,
        ttl_seconds=_INTEGRATION_TTL_SECONDS,
        loader=loader,
    )


async def cached_jev_config(loader: Callable[[], Awaitable[dict]]) -> dict:
    """Cache the Jev runtime config dict (keyed by the jev namespace)."""
    return await cached_value(
        key_prefix="preamble:jev",
        namespace=NS_INTEGRATION_JEV,
        ttl_seconds=_INTEGRATION_TTL_SECONDS,
        loader=loader,
    )


async def cached_facebook_oauth_config(loader: Callable[[], Awaitable[dict]]) -> dict:
    """Cache the Facebook/Meta OAuth config dict (keyed by the facebook namespace).

    Same invalidation semantics as the other integration caches: an admin
    ``PUT /admin/integrations/facebook/credentials`` bumps the namespace version
    so the next read misses and re-reads from Postgres.
    """
    return await cached_value(
        key_prefix="preamble:facebook_oauth",
        namespace=NS_INTEGRATION_FACEBOOK,
        ttl_seconds=_INTEGRATION_TTL_SECONDS,
        loader=loader,
    )


async def cached_system_prompt(
    loader: Callable[[], Awaitable[str]], *, key_suffix: str = "default"
) -> tuple[str, bool]:
    """Cache the fully-assembled system prompt string (keyed by the preamble namespace).

    Returns ``(value, cache_hit)`` so the caller can record whether the prompt
    came from Redis (sub-ms) or was assembled fresh (DB reads). The dashboard
    uses this to distinguish a slow cache-miss (expected once per 10min) from a
    slow Postgres read (actionable).
    """
    # ``str`` is cached as a JSON string scalar; cache_get_json returns it as-is.
    version = await cache_version(NS_PREAMBLE)
    key = f"preamble:system_prompt:{key_suffix}:v{version}"
    cached = await cache_get_json(key)
    if isinstance(cached, str) and cached:
        return cached, True
    value = await loader()
    await cache_set_json(key, value, ttl_seconds=_SYSTEM_PROMPT_TTL_SECONDS)
    return value, False
