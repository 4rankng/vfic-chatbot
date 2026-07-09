"""Zalo OA webhook signature verification — single source of truth.

Zalo signs inbound OA webhooks as ``sha256(appId + data + timeStamp + OAsecretKey)``,
sent in the ``X-ZEvent-Signature`` header as bare hex or ``mac=<hex>`` /
``sha256=<hex>``. ``data`` is the raw request body for normal events (or a nested
``data`` field serialized as compact JSON), and ``timeStamp`` is the
``X-ZEvent-Timestamp`` HEADER value — which need not equal the body's timestamp
field; reading the body field instead of the header is the classic cause of a
permanent 401. We try every (data, timestamp) combination so a genuine signature
matches regardless of form, and report which combination matched.

Shared by the inbound webhook (``app/api/webhooks.py``) and the admin
"verify a captured event" test-connection probe (``app/api/integrations.py``) so
both paths reason about one verifier instead of drifting.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass


def to_json(value: object) -> str:
    """Serialize ``value`` as Zalo's ``JSON.stringify`` would: compact separators,
    non-ASCII kept literal, insertion order preserved (Python dicts are ordered)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def compute_mac(app_id: str, data_text: str, timestamp: str, secret_key: str) -> str:
    """The documented Zalo OA digest: sha256(appId + data + timestamp + secret)."""
    return hashlib.sha256(
        f"{app_id}{data_text}{timestamp}{secret_key}".encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of :func:`verify_signature`.

    ``matched_label`` names the (data, timestamp) combination that matched, e.g.
    ``sha256(app_id+raw_body+header_ts+secret)``, so callers can surface exactly
    which scheme Zalo uses (useful in the admin verify probe).
    """

    verified: bool
    matched_label: str | None = None


def _strip_prefix(signature: str) -> str:
    normalized = (signature or "").strip()
    for prefix in ("sha256=", "mac="):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized


def verify_signature(
    *,
    signature: str,
    raw: bytes,
    payload: dict,
    app_id: str,
    secret_key: str,
    timestamp_header: str = "",
) -> VerifyResult:
    """Verify a Zalo OA webhook signature.

    Returns a :class:`VerifyResult` whose ``verified`` is True iff some
    ``sha256(app_id + data + timestamp + secret)`` digest equals the supplied
    signature (constant-time compare). ``matched_label`` is set when verified.
    """
    if not signature or not app_id or not secret_key:
        return VerifyResult(False)
    normalized = _strip_prefix(signature)

    ts_candidates: list[tuple[str, str]] = []
    if timestamp_header:
        ts_candidates.append(("header_ts", str(timestamp_header)))
    body_ts = (
        payload.get("timestamp") or payload.get("timeStamp") or payload.get("time_stamp")
    )
    if body_ts:
        ts_candidates.append(("body_ts", str(body_ts)))
    if not ts_candidates:
        ts_candidates.append(("no_ts", ""))

    data_candidates: list[tuple[str, str]] = [("raw_body", raw.decode("utf-8", "replace"))]
    data = payload.get("data")
    if data is not None:
        data_candidates.append(("payload.data", to_json(data)))
    data_candidates.append(("full_payload", to_json(payload)))

    for ts_label, ts in ts_candidates:
        for data_label, data_text in data_candidates:
            digest = compute_mac(app_id, data_text, ts, secret_key)
            if hmac.compare_digest(normalized, digest):
                return VerifyResult(
                    True, matched_label=f"sha256(app_id+{data_label}+{ts_label}+secret)"
                )
    return VerifyResult(False)
