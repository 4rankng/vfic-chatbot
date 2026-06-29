"""Best-effort fixed-window rate limiting backed by Redis.

Used to shield expensive auth endpoints (Argon2 password verify on login) from
credential-stuffing / brute-force DoS on the 1-vCPU droplet. Fail-open: a Redis
hiccup never blocks the protected endpoint — auth must stay available, and the
per-chat mutex elsewhere already depends on the same Redis.
"""
import logging

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    # Honour the first hop of X-Forwarded-For (set by Caddy) when present, so
    # requests are bucketed by the real client rather than the edge proxy.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(
    request: Request, prefix: str, limit: int, window: int
) -> None:
    """Reject with 429 once bucket ``rl:<prefix>:<ip>`` exceeds ``limit``/``window``s.

    Disabled in development: the limiter is a production protection against
    credential stuffing / brute force, and dev + the integration suite share the
    loopback IP and issue many legitimate logins — throttling there would both
    annoy local development and flake the test suite.
    """
    if get_settings().app_env == "development":
        return
    key = f"rl:{prefix}:{_client_ip(request)}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        if count > limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Bạn đã thử quá nhiều lần. Vui lòng thử lại sau vài phút.",
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — redis unavailable -> fail open
        logger.warning("rate-limit check skipped for %s (redis unavailable)", prefix)


async def enforce_rate_limit_key(prefix: str, key_part: str, limit: int, window: int) -> None:
    """Reject with 429 for a caller-supplied bucket, e.g. normalized email.

    Like the IP limiter, this is production-only and fail-open on Redis errors.
    """
    if get_settings().app_env == "development":
        return
    safe_key = key_part.strip().lower().replace(" ", "")
    key = f"rl:{prefix}:{safe_key}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        if count > limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Bạn đã thử quá nhiều lần. Vui lòng thử lại sau vài phút.",
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.warning("rate-limit check skipped for %s (redis unavailable)", prefix)
