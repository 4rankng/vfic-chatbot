"""Redis terminal marks for recipients a provider permanently rejected.

When a provider send fails with the invalid-recipient class of error
(``user_unreachable`` — Zalo OA ``-201 user_id is not valid`` or the Bot
Platform's ``user_id is invalid``), retrying the same send can never succeed.
The dispatcher records that once per channel identity so later turns within the
marker TTL can skip the wasted generation/send.

This mirrors the profile-enrichment terminal-marker convention
(:mod:`app.services.profile_enrichment`): a ``sha256(external_id)[:32]`` digest,
a ``{namespace}:unreachable:{digest}`` key, and the same 7-day TTL as the
``done`` marker, so a recipient who later becomes reachable (re-follows, re-adds
the bot) is retried after expiry. The profile helper itself is not reused
because it is profile-scoped and keys on ``external_id`` alone without the
channel, so a Zalo-bot chat id and an OA user id that happen to share a string
would collide; the channel is folded into the namespace here instead.
"""

from __future__ import annotations

import hashlib

# Mirrors ``_PROFILE_LOOKUP_DONE_TTL_SECONDS`` in ``app.services.profile_enrichment``.
_SEND_UNREACHABLE_TTL_SECONDS = 7 * 24 * 60 * 60

# The provider-neutral error class for a permanently invalid recipient. Kept
# in sync with ``app.shared.application.outbound.OutboundErrorClass`` and
# ``app.services.conversation.unreachable.USER_UNREACHABLE_SEND_CLASS`` (the
# value both senders and the send finalizers already key on).
SEND_UNREACHABLE_ERROR_CLASS = "user_unreachable"


def _send_unreachable_key(channel: str, recipient_id: str) -> str:
    """Redis key recording that no send to this channel identity can succeed."""
    namespace = f"send:{channel or 'unknown'}"
    digest = hashlib.sha256(recipient_id.encode("utf-8")).hexdigest()[:32]
    return f"{namespace}:unreachable:{digest}"


async def mark_recipient_unreachable(channel: str, recipient_id: str) -> None:
    """Record that the provider permanently rejects this recipient.

    Set when a send fails with ``user_unreachable``. The marker expires after
    the same 7-day TTL as the profile ``done`` marker, so a user who later
    re-follows is attempted again. Cache writes are best-effort: a Redis failure
    must never break the send finalization that already committed.
    """
    try:
        from app.core.redis import get_redis

        await get_redis().set(
            _send_unreachable_key(channel, recipient_id),
            "1",
            ex=_SEND_UNREACHABLE_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001 -- cache is best-effort
        return


async def is_recipient_unreachable(channel: str, recipient_id: str) -> bool:
    """True when the terminal marker says sends to this identity can never succeed.

    Redis failures report False so dispatch falls back to a real send attempt
    instead of silently dropping a possibly-deliverable reply.
    """
    try:
        from app.core.redis import get_redis

        return bool(
            await get_redis().exists(_send_unreachable_key(channel, recipient_id))
        )
    except Exception:  # noqa: BLE001 -- Redis must never block dispatch
        return False
