"""Best-effort Redis cache for the chatbot's shared preamble.

The preamble is the slow-changing context assembled on every chat turn:
- integration settings (minimax/openrouter) — change only via admin PUT
- the assembled system prompt (persona body + active-product index) — changes
  only on persona/project/index-card edits

These are re-read from Postgres on every turn today; caching them removes
several DB round-trips + AES-GCM decrypts from the hot path. Each entry is
keyed by a version namespace so admin writes invalidate via ``bump_cache_version``.

Cache failures must never affect chat turns. On any Redis error the ``loader``
callable is invoked directly and its result returned unchanged.

The TTLs below are internal tuning constants, not deployment knobs: the preamble
changes only on admin edits (which bump the version immediately), so the TTL is
just a safety net for a missed bump — not a value operators need to tune.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, TypeVar

from app.core.cache import cache_get_json, cache_set_json, cache_version

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Namespaces for version-bump invalidation. ``bump_cache_version(namespace)``
# on the matching write path flips these, so the next read misses and re-reads.
NS_INTEGRATION_MINIMAX = "integration_minimax"
NS_INTEGRATION_OPENROUTER = "integration_openrouter"
NS_INTEGRATION_ZALO = "integration_zalo"
NS_INTEGRATION_FACEBOOK = "integration_facebook"
NS_PREAMBLE = "preamble"

# Integration settings change only via the admin UI; 5 min is a safety net for
# a missed version bump. The system prompt (persona + active-product index)
# changes only on persona/project edits; 10 min mirrors the warm-window intent.
_INTEGRATION_TTL_SECONDS = 300
_SYSTEM_PROMPT_TTL_SECONDS = 600


async def cached_value(
    *,
    key_prefix: str,
    namespace: str,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[T]],
) -> T:
    """Return the cached value for ``key_prefix`` or ``await loader()`` on miss.

    The cache key embeds ``cache_version(namespace)`` so a ``bump_cache_version``
    on the write path invalidates without an explicit delete. Best-effort: any
    Redis error falls through to ``loader``.
    """
    version = await cache_version(namespace)
    key = f"{key_prefix}:v{version}"
    cached = await cache_get_json(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    value = await loader()
    await cache_set_json(key, value, ttl_seconds=ttl_seconds)
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


async def cached_zalo_config(loader: Callable[[], Awaitable[dict]]) -> dict:
    """Cache the zalo runtime config dict (keyed by the zalo namespace)."""
    return await cached_value(
        key_prefix="preamble:zalo",
        namespace=NS_INTEGRATION_ZALO,
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
