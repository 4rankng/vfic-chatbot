"""Redis-backed health of the Zalo OA inbound webhook signature check.

The webhook records the outcome of every real signature verification so the
admin integration status can surface "the stored Webhook Secret is rejecting real
Zalo events" the moment it happens — no Test button needed. The live Test
Connection probe authenticates with the access_token and cannot detect a wrong
secret; this passive signal is what catches it.

Recording is best-effort: a Redis hiccup must NEVER change the webhook's
signature verdict, so every call swallows its own errors.
"""

from __future__ import annotations

import logging
import time

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_KEY = "zalo:oa:signature_health"
_TTL_SECONDS = 30 * 86400  # 30 days


async def record_oa_signature(*, ok: bool) -> None:
    """Record one signature-verification outcome. Never raises."""
    try:
        redis = get_redis()
        now = f"{time.time():.3f}"
        if ok:
            await redis.hset(
                _KEY,
                mapping={
                    "last_status": "verified",
                    "last_ts": now,
                    "consec_failures": "0",
                },
            )
        else:
            await redis.hset(
                _KEY,
                mapping={
                    "last_status": "mismatched",
                    "last_ts": now,
                    "last_mismatch_ts": now,
                },
            )
            await redis.hincrby(_KEY, "consec_failures", 1)
        await redis.expire(_KEY, _TTL_SECONDS)
    except Exception:  # noqa: BLE001 — telemetry must not break the webhook hot path
        logger.debug("zalo OA signature health record failed", exc_info=True)


async def read_oa_signature_health() -> dict | None:
    """Return the recorded health, or None if unavailable/never set."""
    try:
        redis = get_redis()
        raw = await redis.hgetall(_KEY)
    except Exception:  # noqa: BLE001
        logger.debug("zalo OA signature health read failed", exc_info=True)
        return None
    if not raw:
        return None

    def _float(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    out = {
        "last_status": raw.get("last_status"),
        "last_ts": _float(raw.get("last_ts")),
        "last_mismatch_ts": _float(raw.get("last_mismatch_ts")),
        "consec_failures": _int(raw.get("consec_failures")),
    }
    return out
