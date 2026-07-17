"""Messenger messaging-window policy (Phase 5).

The Messenger Platform allows a Page to send a message to a person only within
the ``Standard Messaging Window`` — 24 hours after the person's last message to
the Page. Outside the window, only message tags (confirmed event, human agent,
etc.) or the 24-hour+1 policy are permitted, and V1 deliberately uses none of
those — every outbound must be a reply within the window.

The policy is provider-owned and centrally versioned. The window length is a
constant (revalidate against the official docs on Meta API version bumps). The
caller passes ``last_inbound_at``; the policy never reaches into the DB.

Proactive/outbound sends route through this gate so a follow-up that missed
the window is ``SUPPRESSED`` (acknowledged, not retried) rather than sent and
rejected by Meta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass


#: The Standard Messaging Window is 24 hours from the person's last inbound.
#: Revalidated against the Messenger Platform overview (2026-07-17). Kept as a
#: constant so a Meta policy change is one edit, not a code hunt.
MESSENGER_STANDARD_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of one send-eligibility check."""

    allowed: bool
    reason: str = ""
    # Seconds remaining in the window when ``allowed`` is True; None otherwise.
    # Safe for telemetry (no PII).
    window_remaining_seconds: float | None = None


def evaluate_send_eligibility(
    *, last_inbound_at: datetime | None, now: datetime | None = None
) -> PolicyDecision:
    """Decide whether a Page-originated send is permitted right now.

    ``last_inbound_at`` is the person's most recent inbound to this Page (the
    conversation's ``last_inbound_at``). ``None`` means the person never wrote
    — no window is open, so only an inbound can open one (V1 does not use the
    "Customer Information List" 24h+1 policy).
    """
    if last_inbound_at is None:
        return PolicyDecision(allowed=False, reason="no_inbound_window")
    reference = now or datetime.now(timezone.utc)
    # Normalize tz-naive timestamps (older rows) to UTC for the comparison.
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=timezone.utc)
    elapsed = reference - last_inbound_at
    if elapsed >= MESSENGER_STANDARD_WINDOW:
        return PolicyDecision(allowed=False, reason="window_expired")
    remaining = (MESSENGER_STANDARD_WINDOW - elapsed).total_seconds()
    return PolicyDecision(
        allowed=True,
        window_remaining_seconds=max(0.0, remaining),
    )


__all__ = ["MESSENGER_STANDARD_WINDOW", "PolicyDecision", "evaluate_send_eligibility"]
