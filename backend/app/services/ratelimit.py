"""Per-admin rate limiting for expensive web-process LLM calls.

Extracted from the personas router so the throttle is reusable and testable in isolation.
Fail-open by design: a redis hiccup never blocks the feature (the 1-vCPU droplet's ASGI
worker is the resource being protected, not correctness).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Persona generation: max 5 generates per 600s per admin. A stuck retry loop or
# double-click must not starve the ASGI worker (each generate holds it up to the
# MiniMax timeout).
PERSONA_GEN_RATE_KEY = "persona_gen:{admin_id}"
_PERSONA_GEN_RATE_LIMIT = 5
_PERSONA_GEN_RATE_WINDOW = 600


async def enforce_persona_generate_rate_limit(admin_id: uuid.UUID) -> None:
    try:
        from app.core.redis import get_redis

        r = get_redis()
        key = PERSONA_GEN_RATE_KEY.format(admin_id=admin_id)
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, _PERSONA_GEN_RATE_WINDOW)
        if count > _PERSONA_GEN_RATE_LIMIT:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Bạn đã tạo Agent bằng AI quá nhiều lần. Vui lòng thử lại sau vài phút.",
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — redis unavailable -> fail open
        logger.warning("persona-generate rate-limit check skipped (redis unavailable)")
