"""Facebook Messenger text adapter (Phase 5).

Owns the inbound text normalizer and the outbound Send adapter for the
``facebook_messenger`` provider. The shared graph/ingress/dispatch services
consume the neutral ports (:class:`TextChannelAdapter`, receipt capability);
they never import this module or branch on a Messenger-specific value.

V1 scope (per the deep-interview spec):
- Inbound: candidate ``message.text`` only. Echoes, postbacks, quick replies
  without plain text, attachments, stickers, reactions → acknowledged and
  ignored, with an ignored-reason counter. No media download or persistence.
- Outbound: text only. No buttons/media/templates.
- Policy: enforce the 24-hour Standard Messaging Window via
  :mod:`facebook_policy`; suppress outside-window sends.

Idempotency: the provider message id (``mid``) is the primary dedup key; the
durable boundary is the Phase 2 ``messages(conversation_id, provider_message_id)``
partial unique index. The transient ``message_dedup`` table is a short-window
optimization the ingress service applies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.channels import types as ct
from app.channels.ports import ReceiptCapability, TextChannelAdapter
from app.channels.providers.facebook_oauth import (
    FacebookOAuthError,
    send_message as graph_send_message,
)

if TYPE_CHECKING:
    from app.services.integration_settings import FacebookRuntimeConfig

logger = logging.getLogger(__name__)


# Meta error signals that mean *this recipient* can never be written to again,
# as opposed to a bad request or a dead credential. Kept deliberately narrow:
# stamping ``user_unreachable`` makes the dispatcher record a terminal marker
# (``recipient_marks``) that suppresses every later send to this PSID for its
# full TTL, so a misclassification silently drops messages to a live candidate
# for days. Only signals Meta documents as permanent recipient failures belong
# here; anything unrecognised stays ``provider_error`` (retryable) and is now
# recorded with its code/subcode/detail so a human can extend this list.
#
#   100 / 2018001 — "No matching user found": the PSID is not a sendable
#   thread of this Page (belongs to another Page, or the thread is gone).
_RECIPIENT_UNREACHABLE_CODES: frozenset[tuple[int | None, int | None]] = frozenset({(100, 2018001)})

#   551 — "This person isn't available right now" (any subcode; production
#   observed subcode 1545041): the recipient blocked the Page / messaging or
#   the account is deactivated or restricted. A per-recipient state, proven
#   persistent across bot turns and a recruiter retry on 2026-10-06, and
#   subcode-agnostic in Meta's docs — match on the code alone.
_RECIPIENT_UNREACHABLE_CODES_ANY_SUBCODE: frozenset[int] = frozenset({551})


def _is_recipient_unreachable(exc: FacebookOAuthError) -> bool:
    """Whether Meta refused this PSID permanently rather than the request."""
    if exc.code in _RECIPIENT_UNREACHABLE_CODES_ANY_SUBCODE:
        return True
    return (exc.code, exc.subcode) in _RECIPIENT_UNREACHABLE_CODES


def _rejection_detail(exc: FacebookOAuthError) -> str:
    """A one-line, persistable summary of why Meta refused this send.

    Replaces the bare ``"messenger send rejected"`` that every failure used to
    collapse to. It carries the structured code and subcode plus the sanitized
    provider message, so ``messages.external_error`` and
    ``outbound_outbox.last_error`` are enough to tell a dead credential from a
    dead recipient from a malformed payload without re-running the send.
    """
    parts = [f"code={exc.code}"]
    if exc.subcode is not None:
        parts.append(f"subcode={exc.subcode}")
    line = f"messenger send rejected ({', '.join(parts)})"
    detail = getattr(exc, "detail", None)
    return f"{line}: {detail}" if detail else line


def attribution_from_referral(referral: object) -> dict | None:
    """Map Meta's referral object onto the neutral attribution record.

    Handles both shapes Meta ships: ``message.referral`` on the first message
    of a Click-to-Messenger ad (carries ``ad_id`` plus
    ``ads_context_data.post_id`` / ``ad_title`` — the ad, the ad post, and the
    ad's own creative title behind the thread) and ``postback.referral`` from an
    m.me link / Get Started / QR code (our own ``ref`` only, plus ``source``:
    SHORTLINK or ADS). ``None`` when the object carries nothing beyond its type.

    Note that Meta ships NO ``utm_*`` parameters for a Messenger ad: those are
    appended to website destinations only, and the ``referral`` object has no
    such field. ``ref`` / ``ad_title`` are the whole campaign signal available
    on this path.
    """
    if not isinstance(referral, dict):
        return None
    ads = referral.get("ads_context_data")
    ads = ads if isinstance(ads, dict) else {}
    attribution: dict[str, str] = {"kind": "referral"}
    for key, value in (
        ("post_code", referral.get("ref")),
        ("ad_id", referral.get("ad_id")),
        ("post_id", ads.get("post_id")),
        # The ad's own creative title. Not an ad/campaign id — Meta ships no
        # campaign id here — but it is the one human-written string that says
        # which dự án the ad is for, so it is the fallback for ads that set no
        # custom ``ref``. Resolution lives downstream, never here: this module
        # only maps Meta's payload onto the neutral record.
        ("ad_title", ads.get("ad_title")),
        ("referral_source", referral.get("source")),
    ):
        text = str(value).strip() if value is not None else ""
        if text:
            attribution[key] = text
    return attribution if len(attribution) > 1 else None


class FacebookMessengerNormalizer:
    """Normalize a raw Messenger webhook payload into zero or more events.

    One webhook POST may carry multiple ``entry[]`` blocks, each with multiple
    ``messaging[]`` items. Each item independently reaches a durable outcome
    (persist, ignore, or dedup) — see
    :class:`app.conversation_messaging.application.ingress.InboundIngressResult`.
    The normalizer is pure: it neither persists nor enqueues.

    Only candidate-initiated ``message.text`` events become
    :class:`ChannelInboundMessage`. Everything else (echo, postback, reaction,
    delivery/read receipts, attachments without text, etc.) is ignored here and
    surfaced via :meth:`ignored_summary` for telemetry. Delivery/read are
    handled separately by :meth:`parse_receipt` on the adapter.
    """

    def normalize(self, payload: dict) -> tuple[list[ct.ChannelInboundMessage], dict[str, int]]:
        """Return (inbound_messages, ignored_reason_counts).

        ``ignored_reason_counts`` is a safe telemetry mapping (no PII) of why
        each non-text event was dropped.
        """
        messages: list[ct.ChannelInboundMessage] = []
        ignored: dict[str, int] = {}
        entries = payload.get("entry") or []
        if not isinstance(entries, list):
            return messages, ignored
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            messaging = entry.get("messaging") or []
            if not isinstance(messaging, list):
                continue
            for item in messaging:
                self._normalize_item(item, messages, ignored)
        return messages, ignored

    def _normalize_item(
        self, item: dict, messages: list[ct.ChannelInboundMessage], ignored: dict[str, int]
    ) -> None:
        if not isinstance(item, dict):
            return
        # All Messenger events carry sender.id (the PSID) + recipient.id (the Page id).
        sender = item.get("sender") or {}
        recipient = item.get("recipient") or {}
        timestamp = item.get("timestamp")
        page_id = str(recipient.get("id") or "")
        psid = str(sender.get("id") or "")
        if not page_id or not psid:
            ignored["missing_identity"] = ignored.get("missing_identity", 0) + 1
            return

        # Delivery/read receipts are NOT inbound messages; the adapter parses them.
        if "delivery" in item or "read" in item:
            ignored["receipt_event"] = ignored.get("receipt_event", 0) + 1
            return
        # Echo = the Page's own outbound surfacing back. Never a candidate inbound.
        message = item.get("message") or {}
        if isinstance(message, dict) and message.get("is_echo"):
            ignored["echo"] = ignored.get("echo", 0) + 1
            return
        # Postbacks / quick-replies without plain text: V1 ignores (text-only).
        if "postback" in item:
            ignored["postback"] = ignored.get("postback", 0) + 1
            return
        if not isinstance(message, dict) or "text" not in message:
            # Attachment-only, sticker, reaction, etc.
            ignored["non_text"] = ignored.get("non_text", 0) + 1
            return

        text = message.get("text")
        if not text or not str(text).strip():
            ignored["empty_text"] = ignored.get("empty_text", 0) + 1
            return

        mid = str(message.get("mid") or "")
        if not mid:
            # Meta always sends a mid; a missing one is malformed. Ignore safely.
            ignored["missing_mid"] = ignored.get("missing_mid", 0) + 1
            return

        occurred_at = (
            datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc)
            if timestamp
            else datetime.now(timezone.utc)
        )
        # Meta attaches the referral of a Click-to-Messenger ad to the first
        # message itself; some payloads carry it on the item instead. Either
        # way it rides the neutral type so the persist step can stamp the
        # conversation's first-touch source.
        referral = message.get("referral")
        if not isinstance(referral, dict):
            referral = item.get("referral")
        messages.append(
            ct.ChannelInboundMessage(
                identity=ct.ChannelIdentityRef(
                    provider=ct.PROVIDER_FACEBOOK_MESSENGER,
                    account_key=page_id,
                    external_id=psid,
                ),
                external_message_id=mid,
                text=str(text),
                occurred_at=occurred_at,
                participant_name="",
                attribution=attribution_from_referral(referral),
            )
        )

    @classmethod
    def referrals_from_payload(cls, payload: dict, *, page_id: str) -> list[tuple[str, dict]]:
        """``(psid, attribution)`` for this Page's referral-carrying postbacks.

        The Get Started postback is where Meta puts a new thread's entry source
        (m.me ``ref``, Conversation ad) — before the candidate has typed a
        single message, so nothing else in the pipeline can capture it. Scoped
        to ``page_id`` exactly like the message path: one webhook can carry
        events for every Page the app is subscribed to, and only the connected
        Page's events may touch this deployment. Pure payload scan; persisting
        is the caller's job.
        """
        events: list[tuple[str, dict]] = []
        entries = payload.get("entry") or []
        if not isinstance(entries, list):
            return events
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for item in entry.get("messaging") or []:
                if not isinstance(item, dict):
                    continue
                recipient = item.get("recipient") or {}
                if str(recipient.get("id") or "") != page_id:
                    continue
                postback = item.get("postback")
                if not isinstance(postback, dict):
                    continue
                attribution = attribution_from_referral(postback.get("referral"))
                sender = item.get("sender") or {}
                psid = str(sender.get("id") or "") if isinstance(sender, dict) else ""
                if attribution is not None and psid:
                    events.append((psid, attribution))
        return events

    @staticmethod
    def parse_receipt_from_payload(payload: dict) -> ct.ChannelReceipt | None:
        """Project an already-authenticated webhook payload into a neutral receipt.

        Scans every ``entry[].messaging[]`` for a ``delivery`` or ``read`` block.
        Returns the first receipt found (one POST typically carries one kind).
        Returns ``None`` if the payload carries no receipt.
        """
        entries = payload.get("entry") or []
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            messaging = entry.get("messaging") or []
            if not isinstance(messaging, list):
                continue
            for item in messaging:
                if not isinstance(item, dict):
                    continue
                recipient = item.get("recipient") or {}
                page_id = str(recipient.get("id") or "")
                if not page_id:
                    continue
                if "delivery" in item and isinstance(item["delivery"], dict):
                    mids = item["delivery"].get("mids") or []
                    ts = item["delivery"].get("ts") or item.get("timestamp")
                elif "read" in item and isinstance(item["read"], dict):
                    mids = []  # read events carry only a watermark, not mids
                    ts = item["read"].get("ts") or item.get("timestamp")
                else:
                    continue
                provider_mids = tuple(str(m) for m in mids if m)
                # V1 handles only mid-scoped receipts (delivery events carry
                # mids; read events carry only a watermark). A watermark-only
                # read cannot be matched to a specific outbound message id
                # without a range query, which is deferred. Return None so the
                # caller acknowledges and ignores.
                if not provider_mids:
                    continue
                occurred_at = (
                    datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                    if ts
                    else datetime.now(timezone.utc)
                )
                return ct.ChannelReceipt(
                    provider=ct.PROVIDER_FACEBOOK_MESSENGER,
                    account_key=page_id,
                    provider_message_ids=provider_mids,
                    kind="delivered" if "delivery" in item else "read",
                    occurred_at=occurred_at,
                )
        return None


class FacebookMessengerAdapter(TextChannelAdapter, ReceiptCapability):
    """Send + receipt adapter for the Messenger Platform.

    Resolves the active Page account, validates the command's account key
    matches the connected Page, enforces the response-window policy, builds a
    Graph Send API text payload, and classifies the result via the neutral
    :class:`ChannelSendResult`. No media/buttons methods in V1.
    """

    provider = ct.PROVIDER_FACEBOOK_MESSENGER

    def __init__(self, config: "FacebookRuntimeConfig") -> None:
        self._config = config

    async def send_text(self, command: ct.OutboundTextCommand) -> ct.ChannelSendResult:
        # The dispatch service already validated the channel-account generation
        # fence. Here we additionally require the command's account key to match
        # the connected Page (a stale command for a different Page is suppressed).
        if command.account_key != self._config.page_id:
            return ct.ChannelSendResult(
                ok=False,
                error="command account_key does not match the active Page",
                error_class="provider_error",
                suppressed=True,
            )
        # The Messenger outbox dispatcher enforces the standard messaging window
        # from the authoritative Conversation.last_inbound_at before constructing
        # this adapter command. Direct adapter callers are transport-level tests or
        # provider infrastructure and do not carry conversation state.
        try:
            data = await graph_send_message(
                self._config,
                recipient_psid=command.recipient_id,
                text=command.text,
            )
        except FacebookOAuthError as exc:
            # Classify auth-revoked distinctly so the resolver can mark the
            # account unhealthy; everything else is a provider error. Meta's
            # canonical auth signal is error code 190 (invalid/expired/revoked
            # access token). Substring-matching the message text is unreliable
            # (localized, varies by subcode), so branch on the structured code.
            if exc.code == 190:
                return ct.ChannelSendResult(
                    ok=False,
                    error="page access token invalid or revoked",
                    error_class="auth_revoked",
                )
            detail = _rejection_detail(exc)
            if _is_recipient_unreachable(exc):
                # Permanent per-recipient refusal: the dispatcher stamps a
                # terminal marker for this PSID so later turns stop paying for
                # a full generation + send cycle that cannot succeed.
                logger.warning(
                    "messenger send rejected: recipient unreachable (code=%s subcode=%s page=%s)",
                    exc.code,
                    exc.subcode,
                    self._config.page_id,
                )
                return ct.ChannelSendResult(
                    ok=False,
                    error=detail,
                    error_class="user_unreachable",
                )
            # Log the structured reason (no token, no recipient id) so a
            # rejection is diagnosable from logs alone. Previously nothing was
            # logged at all and the reason never left this frame.
            logger.warning(
                "messenger send rejected (code=%s subcode=%s page=%s): %s",
                exc.code,
                exc.subcode,
                self._config.page_id,
                getattr(exc, "detail", None) or "no provider detail",
            )
            return ct.ChannelSendResult(
                ok=False,
                error=detail,
                error_class="provider_error",
            )
        mid = data.get("message_id") or data.get("recipient_id")
        return ct.ChannelSendResult(
            ok=True,
            provider_message_id=str(mid) if mid else None,
        )

    def parse_receipt(self, payload: dict) -> ct.ChannelReceipt | None:
        return FacebookMessengerNormalizer.parse_receipt_from_payload(payload)


__all__ = [
    "FacebookMessengerNormalizer",
    "FacebookMessengerAdapter",
    "attribution_from_referral",
]
