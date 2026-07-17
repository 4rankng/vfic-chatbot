"""Messenger webhook signature verification (Phase 5).

Meta signs every Event Notification payload with HMAC-SHA256 using the App
Secret and includes the signature in the ``X-Hub-Signature-256`` header as
``sha256=<hexdigest>``. Verification MUST hash the RAW request body bytes —
re-serializing JSON (reordering/pretty-printing) breaks the signature, which
is the #1 community-reported failure mode.

The verifier is provider-owned and stateless. It never logs the body or the
app secret. A constant-time compare prevents timing oracles on the signature.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class SignatureVerification:
    """Result of verifying one POST webhook body."""

    verified: bool
    # Safe to log; never includes the body or the secret.
    reason: str = ""


def verify_messenger_signature(
    *, signature_header: str, raw_body: bytes, app_secret: str
) -> SignatureVerification:
    """Verify ``X-Hub-Signature-256`` against the raw body.

    Returns ``verified=False`` (never raises) for any missing/empty/malformed
    input so the caller can ack-and-drop uniformly. The compare is constant
    time via :func:`hmac.compare_digest`.

    A missing app secret is treated as "not verified" rather than raising —
    the caller decides whether dev-mode accepts unsigned traffic.
    """
    if not app_secret:
        return SignatureVerification(verified=False, reason="app_secret_not_configured")
    if not signature_header:
        return SignatureVerification(verified=False, reason="missing_signature_header")
    # Meta's format is "sha256=<hex>". Some integrations send bare hex; accept both.
    expected_prefix = "sha256="
    if signature_header.startswith(expected_prefix):
        sent_hex = signature_header[len(expected_prefix):]
    else:
        sent_hex = signature_header
    try:
        sent_digest = bytes.fromhex(sent_hex)
    except ValueError:
        return SignatureVerification(verified=False, reason="malformed_signature_hex")
    if not sent_digest:
        return SignatureVerification(verified=False, reason="empty_signature")

    computed = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    if hmac.compare_digest(computed, sent_digest):
        return SignatureVerification(verified=True)
    return SignatureVerification(verified=False, reason="signature_mismatch")


def constant_time_verify_token(*, sent: str, expected: str) -> bool:
    """Constant-time compare for the GET webhook challenge verify token.

    Prevents a timing oracle on the configured ``meta_webhook_verify_token``.
    """
    if not expected:
        return False
    return hmac.compare_digest(sent or "", expected)


__all__ = ["SignatureVerification", "verify_messenger_signature", "constant_time_verify_token"]
