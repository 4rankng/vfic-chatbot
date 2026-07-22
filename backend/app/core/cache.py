"""Best-effort Redis cache helpers.

Cache failures must never affect chat turns or dashboard reads. Callers use
short TTLs plus versioned keys for data that changes often.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


async def cache_get_json(key: str) -> Any | None:
    try:
        raw = await get_redis().get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.debug("cache get failed for key %s", key, exc_info=True)
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    try:
        await get_redis().set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except Exception:  # noqa: BLE001
        logger.debug("cache set failed for key %s", key, exc_info=True)


async def cache_version(namespace: str) -> str:
    key = f"cachever:{namespace}"
    try:
        value = await get_redis().get(key)
        return str(value or "1")
    except Exception:  # noqa: BLE001
        logger.debug("cache version read failed for namespace %s", namespace, exc_info=True)
        return "1"


async def bump_cache_version(namespace: str) -> bool:
    key = f"cachever:{namespace}"
    try:
        redis = get_redis()
        created = await redis.set(key, "2", nx=True)
        if not created:
            await redis.incr(key)
        return True
    except Exception:  # noqa: BLE001
        # A missed bump (e.g. transient Redis hiccup during a persona/project
        # save) leaves stale prompts until the TTL expires. WARNING keeps it
        # operator-visible instead of buried at DEBUG.
        logger.warning(
            "cache version bump failed for namespace %s", namespace, exc_info=True
        )
        return False


async def bump_kb_caches() -> bool:
    """Invalidate both KB-backed caches together on any KB content mutation.

    The exact-hash RAG cache (``rag:knowledge:{...}``) reads the ``knowledge``
    version namespace; the semantic RAG cache reads ``semantic_cache``. A KB
    write must bump both so a future enablement of the semantic cache cannot
    serve stale facts. Best-effort like the underlying helpers: a Redis failure
    is logged at debug and never surfaces to the caller.
    """
    knowledge_ok = await bump_cache_version("knowledge")
    semantic_ok = await bump_cache_version("semantic_cache")
    return knowledge_ok and semantic_ok
