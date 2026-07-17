"""Neutral channel value objects and send results.

Every type here is provider-neutral and immutable. They carry no Zalo or
Facebook field names, no credentials, and no raw provider envelopes. Secrets,
tokens, raw webhook bodies, and full external identifiers must never appear in
these types or in their ``repr``.

Design rules (Phase 1 contract):

1. **Identity is account-scoped.** A participant is uniquely identified by
   ``(provider, account_key, external_id)`` — never by an external ID alone
   (a PSID is Page-scoped; a Zalo chat id is provider-scoped).
2. **Text-only in V1.** Inbound carries candidate ``text`` only; outbound
   carries ``text`` only. Non-text events are acknowledged and ignored at the
   provider edge and never reach these types.
3. **Ambiguous transport maps to SEND_UNKNOWN.** ``ChannelSendResult.error_class``
   reuses the existing ``app.graph.send_classification`` taxonomy so the
   shared delivery state machine does not branch on provider.
4. **Redacted repr.** External identifiers are masked in diagnostics so a stray
   ``repr()`` in a log line cannot leak a PSID or chat id.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.graph.outbound_telemetry import OutboundTelemetry
from app.graph.send_classification import AMBIGUOUS_SEND_CLASSES


# ---------------------------------------------------------------------------
# Provider identification
# ---------------------------------------------------------------------------

#: Provider IDs are validated strings, not a closed enum. Only installed
#: adapters register an ID; speculative future providers (Telegram, WhatsApp)
#: are deliberately absent so a typo cannot select a non-existent provider.
PROVIDER_ZALO_BOT = "zalo_bot"
PROVIDER_ZALO_OA = "zalo_oa"
PROVIDER_FACEBOOK_MESSENGER = "facebook_messenger"

_INSTALLED_PROVIDERS = frozenset(
    {PROVIDER_ZALO_BOT, PROVIDER_ZALO_OA, PROVIDER_FACEBOOK_MESSENGER}
)


def is_known_provider(provider: str) -> bool:
    """True when ``provider`` matches an installed adapter ID.

    Business logic should resolve through :class:`ChannelAdapterRegistry`
    rather than branching on this predicate. It exists for input validation
    at trust boundaries (e.g. an API scope parameter).
    """
    return provider in _INSTALLED_PROVIDERS


# ---------------------------------------------------------------------------
# Identity and account references
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelIdentityRef:
    """Canonical participant key: ``(provider, account_key, external_id)``.

    Examples:
      - Zalo Bot:  ``("zalo_bot", "default:zalo_bot", "<chat_id>")``
      - Zalo OA:   ``("zalo_oa",  "default:zalo_oa",  "<oa_user_id>")``
      - Messenger: ``("facebook_messenger", "<page_id>", "<PSID>")``

    ``account_key`` is the immutable provider/account identifier (a Page ID for
    Messenger, a stable synthetic key for the single-tenant Zalo adapters).
    ``external_id`` is the participant's id *within that account scope*.
    """

    provider: str
    account_key: str
    external_id: str

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("ChannelIdentityRef.provider is required")
        if not self.account_key:
            raise ValueError("ChannelIdentityRef.account_key is required")
        if not self.external_id:
            raise ValueError("ChannelIdentityRef.external_id is required")

    def __repr__(self) -> str:  # noqa: D401 - redacted by design
        return (
            f"ChannelIdentityRef(provider={self.provider!r}, "
            f"account_key={_redact(self.account_key)!r}, "
            f"external_id={_redact(self.external_id)!r})"
        )


@dataclass(frozen=True)
class ChannelAccountRef:
    """Lightweight reference to a channel account authority record.

    Mirrors the durable ``ChannelAccount`` row without coupling this contract
    layer to the ORM. ``status`` is the account lifecycle status
    (``ACTIVE``/``INACTIVE``); ``generation`` is the authority epoch advanced
    on connect/reconnect/disconnect so a stale outbound command can detect
    that its authority has been superseded.

    The full ORM model is added in Phase 2; this value object is the
    provider-neutral shape shared across layers.
    """

    id: str
    provider: str
    account_key: str
    label: str
    status: str
    generation: int

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ChannelAccountRef.id is required")
        if not self.provider:
            raise ValueError("ChannelAccountRef.provider is required")
        if not self.account_key:
            raise ValueError("ChannelAccountRef.account_key is required")
        if self.status not in ("ACTIVE", "INACTIVE"):
            raise ValueError(
                f"ChannelAccountRef.status must be ACTIVE or INACTIVE, got {self.status!r}"
            )
        if self.generation < 0:
            raise ValueError("ChannelAccountRef.generation must be non-negative")

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    def __repr__(self) -> str:  # noqa: D401 - redacted by design
        # ``label`` is the safe display name; account_key may be an external ID
        # (Page ID), so redact it. ``id`` is an internal UUID — safe to print.
        return (
            f"ChannelAccountRef(id={self.id!r}, provider={self.provider!r}, "
            f"account_key={_redact(self.account_key)!r}, label={self.label!r}, "
            f"status={self.status!r}, generation={self.generation})"
        )


# ---------------------------------------------------------------------------
# Inbound / outbound contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelInboundMessage:
    """Provider-neutral inbound text from one participant.

    Only text is represented in V1. Non-text events are acknowledged and
    ignored at the provider edge and never reach this type. ``trace_id`` is
    the end-to-end correlation id propagated through RQ → BotRun → logs.
    """

    identity: ChannelIdentityRef
    external_message_id: str
    text: str
    occurred_at: datetime
    trace_id: str | None = None
    participant_name: str = ""

    def __post_init__(self) -> None:
        if not self.external_message_id:
            raise ValueError("ChannelInboundMessage.external_message_id is required")
        # Empty text is rejected at the provider edge (it never produces a
        # bot turn), but a non-empty check here defends against a misrouted
        # event slipping through. Whitespace-only text is the caller's call.
        if self.text is None or self.text == "":
            raise ValueError("ChannelInboundMessage.text is required")

    def __repr__(self) -> str:  # noqa: D401 - redacted by design
        # Never expose candidate text or full external ids in repr.
        return (
            f"ChannelInboundMessage(identity={self.identity!r}, "
            f"external_message_id={_redact(self.external_message_id)!r}, "
            f"text=<redacted>, occurred_at={self.occurred_at!r}, "
            f"trace_id={self.trace_id!r})"
        )


@dataclass(frozen=True)
class OutboundTextCommand:
    """Durable provider-neutral send command for one outbound text.

    ``account_key`` and ``recipient_id`` are the provider/account-scoped
    destination; ``generation`` is the authority fence stamped at command
    creation and revalidated immediately before provider I/O so a stale
    command (e.g. queued across a disconnect) is suppressed rather than sent.

    ``reply_to_message_id`` is optional and provider-neutral; the adapter
    decides whether/how to quote it (e.g. Zalo OA quote, Messenger no-quote).
    """

    provider: str
    account_key: str
    recipient_id: str
    text: str
    channel_account_generation: int
    reply_to_message_id: str | None = None

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("OutboundTextCommand.provider is required")
        if not self.account_key:
            raise ValueError("OutboundTextCommand.account_key is required")
        if not self.recipient_id:
            raise ValueError("OutboundTextCommand.recipient_id is required")
        if self.text is None or self.text == "":
            raise ValueError("OutboundTextCommand.text is required")
        if self.channel_account_generation < 0:
            raise ValueError(
                "OutboundTextCommand.channel_account_generation must be non-negative"
            )

    def __repr__(self) -> str:  # noqa: D401 - redacted by design
        reply = (
            _redact(self.reply_to_message_id) if self.reply_to_message_id else None
        )
        return (
            f"OutboundTextCommand(provider={self.provider!r}, "
            f"account_key={_redact(self.account_key)!r}, "
            f"recipient_id={_redact(self.recipient_id)!r}, text=<redacted>, "
            f"channel_account_generation={self.channel_account_generation}, "
            f"reply_to_message_id={reply!r})"
        )


# ---------------------------------------------------------------------------
# Send result / receipt
# ---------------------------------------------------------------------------

#: Outcome bucket for a send attempt. Mirrors the existing graph taxonomy.
ChannelErrorClass = Literal[
    "connect_error",      # pre-send; retryable (FAILED)
    "read_timeout",       # post-send ambiguity; non-retriable (SEND_UNKNOWN)
    "remote_protocol_error",
    "read_error",
    "unknown",            # conservative default → SEND_UNKNOWN
    "provider_error",     # provider returned a definite failure envelope
    "policy_suppressed",  # provider policy (e.g. messaging window) blocked send
    "auth_revoked",       # credential revoked; fail closed, surface reconnect
]


@dataclass(frozen=True)
class ChannelSendResult:
    """Result of one outbound send attempt.

    Reuses the existing ``error_class`` taxonomy so the shared delivery state
    machine (``app.graph.send_classification``) needs no provider branching.
    ``suppressed`` marks a policy or stale-authority suppression: not a
    provider failure, not retriable as a transport error.

    ``telemetry`` reuses :class:`OutboundTelemetry` so dashboards keep one
    adapter-rollup shape. It excludes text, recipient ids, and credentials.

    ``error_class`` is **required when ``ok`` is False**: every failure must
    be classified so the SEND_UNKNOWN vs FAILED decision is explicit. A wrapper
    that constructs ``ChannelSendResult(ok=False, error=...)`` without an
    ``error_class`` would otherwise silently route to retryable FAILED — the
    opposite of the at-most-once bias the taxonomy enforces. Construction
    refuses such a result rather than guessing.
    """

    ok: bool
    provider_message_id: str | None = None
    error: str | None = None
    error_class: ChannelErrorClass | None = None
    suppressed: bool = False
    telemetry: OutboundTelemetry | None = None

    def __post_init__(self) -> None:
        if not self.ok and self.error_class is None:
            raise ValueError(
                "ChannelSendResult.error_class is required when ok=False: "
                "every failure must be classified (connect_error=retryable, "
                "read_timeout/unknown/...=SEND_UNKNOWN, provider_error=retryable, "
                "policy_suppressed/auth_revoked=fail-closed)"
            )

    @property
    def is_send_unknown(self) -> bool:
        """True when this result must route to non-retriable ``SEND_UNKNOWN``.

        Reuses :data:`AMBIGUOUS_SEND_CLASSES` so the rule lives in one place.
        A suppressed result is never SEND_UNKNOWN (it was deliberately not
        sent), and a definite provider error is retryable ``FAILED``.
        """
        if self.ok or self.suppressed:
            return False
        return self.error_class in AMBIGUOUS_SEND_CLASSES

    def __repr__(self) -> str:  # noqa: D401 - redacted by design
        # ``error`` text can echo provider envelopes; keep only the class.
        return (
            f"ChannelSendResult(ok={self.ok}, "
            f"provider_message_id={_redact(self.provider_message_id)!r}, "
            f"error_class={self.error_class!r}, suppressed={self.suppressed})"
        )


#: Receipt kind. Monotonic: SENT → DELIVERED → READ; lower kinds never
#: overwrite a higher one.
ChannelReceiptKind = Literal["sent", "delivered", "read"]


@dataclass(frozen=True)
class ChannelReceipt:
    """Provider-neutral delivery/read receipt, scoped to one account.

    ``provider_message_ids`` are the provider's own message ids (e.g. Zalo OA
    message ids, Messenger mids) for outbound rows in *this* account scope.
    Cross-account/cross-provider id collisions are impossible because receipt
    application is always scoped through the owning conversation identity.
    """

    provider: str
    account_key: str
    provider_message_ids: tuple[str, ...]
    kind: ChannelReceiptKind
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("ChannelReceipt.provider is required")
        if not self.account_key:
            raise ValueError("ChannelReceipt.account_key is required")
        if not self.provider_message_ids:
            raise ValueError("ChannelReceipt.provider_message_ids is required")
        if self.kind not in ("sent", "delivered", "read"):
            raise ValueError(f"ChannelReceipt.kind invalid: {self.kind!r}")

    def __repr__(self) -> str:  # noqa: D401 - redacted by design
        ids = ", ".join(_redact(mid) for mid in self.provider_message_ids)
        return (
            f"ChannelReceipt(provider={self.provider!r}, "
            f"account_key={_redact(self.account_key)!r}, "
            f"provider_message_ids=({ids}), kind={self.kind!r})"
        )


# ---------------------------------------------------------------------------
# Redaction helper
# ---------------------------------------------------------------------------


def _redact(value: str | None) -> str:
    """Mask all but the last 4 chars of a sensitive identifier.

    Short values (≤4 chars) collapse to a fixed-length mask so the original
    length is not recoverable. ``None`` stays ``None``. Used only by ``repr``
    — the underlying value is unchanged.
    """
    if value is None:
        return "None"
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


__all__ = [
    "PROVIDER_ZALO_BOT",
    "PROVIDER_ZALO_OA",
    "PROVIDER_FACEBOOK_MESSENGER",
    "is_known_provider",
    "ChannelIdentityRef",
    "ChannelAccountRef",
    "ChannelInboundMessage",
    "OutboundTextCommand",
    "ChannelSendResult",
    "ChannelReceipt",
    "ChannelReceiptKind",
    "ChannelErrorClass",
]
