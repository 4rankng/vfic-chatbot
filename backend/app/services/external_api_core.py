"""Shared primitives for outbound integrations the model drives.

The deployment-wide TingTing password-reset integration needs this boundary: the
operator fixes the origin, the model may only choose a relative path plus the
method, parameters are a flat bounded map, mutating calls are throttled, and
every expected failure is a *state* rather than an exception so the agent can say
truthfully that it could not do the thing. Any future integration the model
drives should reuse it rather than re-derive the guards.

This module is deliberately transport-free (it never imports ``get_http_client``):
each integration owns its single egress call site, and this file owns only the
validation, the outcome shape and the Redis admission buckets.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

EXTERNAL_API_TIMEOUT_SECONDS = 8.0
EXTERNAL_API_MAX_RESPONSE_CHARS = 4000
EXTERNAL_API_MAX_PARAMS = 10
EXTERNAL_API_MAX_PARAM_CHARS = 200
EXTERNAL_API_DEDUPE_SECONDS = 60
EXTERNAL_API_ENDPOINT_CEILING = 60
EXTERNAL_API_ENDPOINT_WINDOW_SECONDS = 60
EXTERNAL_API_ALLOWED_METHODS = ("GET", "POST")
# http is accepted only for a loopback host so a dev/smoke server on
# 127.0.0.1:<port> works without weakening the production rule.
EXTERNAL_API_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class ExternalApiOutcome(NamedTuple):
    """The only value crossing from a service back into the graph layer."""

    state: str
    project_label: str | None
    path: str
    status_code: int | None
    text: str
    detail: str = ""


def normalize_base_url(value: str) -> str:
    """Validate an absolute base URL and return it without a trailing slash.

    ``https`` is required except for a loopback host, where plain ``http`` is
    accepted for local development and smoke runs. Userinfo, a query string and
    a fragment are all rejected — each would let a stored value point somewhere
    other than the origin the operator reviewed.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("base_url_required")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("base_url_scheme")
    if parsed.username or parsed.password:
        raise ValueError("base_url_credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url_invalid")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("base_url_host")
    if parsed.scheme == "http" and host not in EXTERNAL_API_LOCAL_HOSTS:
        raise ValueError("base_url_scheme")
    return raw.rstrip("/")


def normalize_endpoint_path(value: str) -> str:
    """Validate a relative request path (``/v1/...``); reject anything absolute.

    This is the origin guard: the model supplies the path, so a value carrying a
    scheme, an authority (``//host``) or a traversal segment must never reach the
    request builder.
    """
    raw = (value or "").strip()
    if not raw or not raw.startswith("/"):
        raise ValueError("path_invalid")
    if "://" in raw or "//" in raw or ".." in raw or "?" in raw or "#" in raw:
        raise ValueError("path_invalid")
    return raw


def normalize_method(value: str) -> str:
    """Fold a model-supplied method onto the allowed set."""
    method = (value or "").strip().upper()
    if method not in EXTERNAL_API_ALLOWED_METHODS:
        raise ValueError("method_not_allowed")
    return method


def sanitize_params(params: object) -> dict[str, str] | None:
    """Coerce model-supplied params into a flat ``str -> str`` mapping.

    ``None`` means "reject": a container value, an over-long value, or more
    parameters than the ceiling. Empty/``None`` values are dropped rather than
    sent as empty strings.
    """
    if params is None:
        return {}
    if not isinstance(params, dict):
        return None
    clean: dict[str, str] = {}
    for raw_key, raw_value in params.items():
        if isinstance(raw_value, (dict, list, tuple, set, frozenset)):
            return None
        text = "" if raw_value is None else str(raw_value).strip()
        if not text:
            continue
        if len(text) > EXTERNAL_API_MAX_PARAM_CHARS:
            return None
        name = str(raw_key).strip()
        if not name:
            continue
        clean[name] = text
    if len(clean) > EXTERNAL_API_MAX_PARAMS:
        return None
    return clean


class QuotaDecision(NamedTuple):
    """Admission result: allowed, or the bucket that refused and why."""

    allowed: bool
    reason: str = ""  # "duplicate" | "ceiling"


async def consume_write_quota(
    scope: str, params: dict[str, Any], *, dedupe: bool = True
) -> QuotaDecision:
    """Two buckets for a mutating call: identical-params dedupe, then ceiling.

    ``scope`` names the integration and the target (method + path), never a
    secret: the dedupe key is a digest of the parameters, so no plaintext value
    (a phone number, an OTP code) reaches Redis.

    ``dedupe=False`` keeps only the ceiling. A read-only call the model may
    legitimately repeat — re-reading a record to compare an identity — must not
    be refused as a duplicate; the ceiling still bounds egress.
    """
    digest = hashlib.sha256(
        json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if dedupe and not await _consume_window(
        f"extapi:dedupe:{scope}:{digest}",
        limit=1,
        window=EXTERNAL_API_DEDUPE_SECONDS,
    ):
        return QuotaDecision(False, "duplicate")
    if not await _consume_window(
        f"extapi:ceiling:{scope}",
        limit=EXTERNAL_API_ENDPOINT_CEILING,
        window=EXTERNAL_API_ENDPOINT_WINDOW_SECONDS,
    ):
        return QuotaDecision(False, "ceiling")
    return QuotaDecision(True)


async def _consume_window(key: str, *, limit: int, window: int) -> bool:
    """Fixed-window admission check; fail-open when Redis is unavailable."""
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        return count <= limit
    except Exception as exc:  # noqa: BLE001 — a Redis hiccup must not block the call
        logger.warning("external api throttle skipped error_type=%s", type(exc).__name__)
        return True


__all__ = [
    "EXTERNAL_API_ALLOWED_METHODS",
    "EXTERNAL_API_DEDUPE_SECONDS",
    "EXTERNAL_API_ENDPOINT_CEILING",
    "EXTERNAL_API_ENDPOINT_WINDOW_SECONDS",
    "EXTERNAL_API_LOCAL_HOSTS",
    "EXTERNAL_API_MAX_PARAMS",
    "EXTERNAL_API_MAX_PARAM_CHARS",
    "EXTERNAL_API_MAX_RESPONSE_CHARS",
    "EXTERNAL_API_TIMEOUT_SECONDS",
    "ExternalApiOutcome",
    "QuotaDecision",
    "consume_write_quota",
    "normalize_base_url",
    "normalize_endpoint_path",
    "normalize_method",
    "sanitize_params",
]
