"""Narrow provider-neutral Protocols and capability markers.

Design (Phase 1):

- :class:`TextChannelAdapter` is the *only* required method. Business logic
  depends on this Protocol, never on a concrete adapter class.
- Optional behaviors (typing indicator, receipt parsing) are **separate**
  capability Protocols, not no-op methods on the base adapter. A caller asks
  the registry for the capability and gets ``None`` if the adapter does not
  implement it — no ``hasattr`` checks in business logic.
- Credential/token resolution stays **outside** adapter method signatures.
  Adapters resolve authority through :class:`ChannelAccountResolver` or a
  provider-owned resolver; the shared command carries only the account key
  and the immutable authority generation fence.

These ports are deliberately minimal. Phase 3 wires concrete Zalo wrappers
behind them; Phase 5 adds the Messenger adapter. No provider-specific import
should ever appear in a shared service module.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.channels.types import (
    ChannelAccountRef,
    ChannelReceipt,
    ChannelSendResult,
    OutboundTextCommand,
)


@runtime_checkable
class TextChannelAdapter(Protocol):
    """Required: send one outbound text through a provider.

    The adapter is responsible for:

    - Resolving the active account authority for its own provider.
    - Validating that ``command.account_key`` matches the active account.
    - Re-validating ``command.channel_account_generation`` immediately before
      provider I/O (the authority fence).
    - Enforcing provider-owned send policy (e.g. Messenger response window).
    - Classifying the transport result using :class:`ChannelSendResult` with
      the shared ``error_class`` taxonomy.
    """

    provider: str

    async def send_text(self, command: OutboundTextCommand) -> ChannelSendResult: ...


@runtime_checkable
class TypingCapability(Protocol):
    """Optional: emit a typing indicator (Zalo Bot yes, Zalo OA / Messenger no).

    Absence of this capability means "do nothing" — *not* a failed message.
    """

    provider: str

    async def send_typing(
        self, *, account_key: str, recipient_id: str
    ) -> ChannelSendResult: ...


@runtime_checkable
class ReceiptCapability(Protocol):
    """Optional: parse provider delivery/read webhook events into receipts.

    Providers that do not emit receipts (Zalo Bot) do not implement this. The
    receipt is already provider-neutral; application is scoped through the
    owning conversation identity by the shared delivery finalizer.
    """

    provider: str

    def parse_receipt(self, payload: dict) -> ChannelReceipt | None:
        """Return a neutral receipt, or ``None`` if the event is not a receipt.

        ``payload`` is the raw, already-authenticated provider event. The
        adapter must not perform any I/O here; it only normalizes.
        """
        ...


@runtime_checkable
class ChannelAccountResolver(Protocol):
    """Resolve active account authority for a provider/account pair.

    Implementations fail **closed** for inactive or unknown accounts: an
    inactive Page is a readable history scope but never resolves send
    authority. The resolver never assumes one global account per provider —
    the account key is always part of the lookup.
    """

    async def resolve_active(
        self, *, provider: str, account_key: str
    ) -> ChannelAccountRef | None:
        """Return the active account ref, or ``None`` if none is active.

        ``None`` suppresses outbound dispatch and surfaces read-only behavior
        for the inbox. It is never an error to ask about an inactive account.
        """
        ...

    async def resolve_any(
        self, *, provider: str, account_key: str
    ) -> ChannelAccountRef | None:
        """Return the account ref regardless of lifecycle status (history scope).

        Used by inbox reads that must show archived Page conversations as
        read-only. Returns ``None`` only when the account does not exist.
        """
        ...


__all__ = [
    "TextChannelAdapter",
    "TypingCapability",
    "ReceiptCapability",
    "ChannelAccountResolver",
]
