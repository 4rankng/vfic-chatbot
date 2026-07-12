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


async def bump_cache_version(namespace: str) -> None:
    key = f"cachever:{namespace}"
    try:
        await get_redis().incr(key)
    except Exception:  # noqa: BLE001
        logger.debug("cache version bump failed for namespace %s", namespace, exc_info=True)
