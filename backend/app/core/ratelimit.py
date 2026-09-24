"""Best-effort fixed-window rate limiting backed by Redis.

Used to shield expensive auth endpoints (Argon2 password verify on login) from
credential-stuffing / brute-force DoS on the 1-vCPU droplet, and the
LLM/embedding-backed routes from a single authenticated user draining the
deployment-wide token lists (SEC-04). Default is fail-open: a Redis hiccup never
blocks the protected endpoint — auth must stay available, and the per-chat mutex
elsewhere already depends on the same Redis. Callers that guard a scarce
deployment-wide resource can opt into ``fail_open=False`` (see
``ratelimit_llm_fail_closed``).

API routers reach this module through ``app.shared.infrastructure.rate_limits``:
``app/api/*`` may not import ``app.core`` (enforced by
``tests/test_architecture_boundaries.py``).
"""

import logging

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_TOO_MANY_REQUESTS = "Bạn đã thử quá nhiều lần. Vui lòng thử lại sau vài phút."
_LIMITER_UNAVAILABLE = (
    "Dịch vụ tạm thời không thể kiểm tra giới hạn yêu cầu. "
    "Vui lòng thử lại sau vài phút."
)


def _client_ip(request: Request) -> str:
    # Honour the first hop of X-Forwarded-For (set by Caddy) when present, so
    # requests are bucketed by the real client rather than the edge proxy.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    return client.host if client is not None else "unknown"


async def _enforce_bucket(
    key: str,
    *,
    prefix: str,
    limit: int,
    window: int,
    fail_open: bool,
) -> None:
    """Increment ``key`` and reject with 429 once it exceeds ``limit``/``window``s."""
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        if count > limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _TOO_MANY_REQUESTS)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — redis unavailable -> fail open unless asked
        if fail_open:
            logger.warning("rate-limit check skipped for %s (redis unavailable)", prefix)
            return
        # Fail closed: the caller guards a deployment-wide resource (LLM/embed
        # token lists), so an unverifiable budget must deny rather than admit.
        # Only the exception type is logged — a Redis error string can echo the
        # connection target.
        logger.error(
            "rate-limit check unavailable for %s (redis error=%s, failing closed)",
            prefix,
            type(exc).__name__,
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, _LIMITER_UNAVAILABLE
        ) from None


async def enforce_rate_limit(
    request: Request,
    prefix: str,
    limit: int,
    window: int,
    *,
    fail_open: bool = True,
) -> None:
    """Reject with 429 once bucket ``rl:<prefix>:<ip>`` exceeds ``limit``/``window``s.

    Disabled in development: the limiter is a production protection against
    credential stuffing / brute force, and dev + the integration suite share the
    loopback IP and issue many legitimate logins — throttling there would both
    annoy local development and flake the test suite.
    """
    if get_settings().app_env == "development":
        return
    await _enforce_bucket(
        f"rl:{prefix}:{_client_ip(request)}",
        prefix=prefix,
        limit=limit,
        window=window,
        fail_open=fail_open,
    )


async def enforce_rate_limit_key(
    prefix: str,
    key_part: str,
    limit: int,
    window: int,
    *,
    fail_open: bool = True,
) -> None:
    """Reject with 429 for a caller-supplied bucket, e.g. normalized email or user id.

    Like the IP limiter, this is production-only and fail-open on Redis errors
    unless the caller passes ``fail_open=False``.
    """
    if get_settings().app_env == "development":
        return
    safe_key = key_part.strip().lower().replace(" ", "")
    await _enforce_bucket(
        f"rl:{prefix}:{safe_key}",
        prefix=prefix,
        limit=limit,
        window=window,
        fail_open=fail_open,
    )
