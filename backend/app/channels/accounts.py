"""Neutral account-lifecycle status and an in-memory resolver for tests.

Phase 1 defines the *contract* for account authority. The real resolver is
backed by the ``ChannelAccount`` ORM model added in Phase 2, with encrypted
credentials resolved provider-side (Phase 4 for Messenger). This module
provides:

- :data:`ChannelAccountStatus` — lifecycle status constants.
- :class:`InMemoryAccountResolver` — a test/double resolver used by the
  conformance suite. Production code never imports it.

Capability semantics (per the Phase 1 spec):

- ``ACTIVE``  — resolves send authority; full recruiter parity.
- ``INACTIVE`` — readable history scope; never resolves send authority. Send,
  retry, takeover/resume, and other send-capable mutations fail closed.

V1 enforces *at most one* active ``facebook_messenger`` account at the
registry/persistence layer (Phase 2 partial uniqueness). The resolver here is
permissive (it trusts what it is handed) because it is a test double.
"""

from __future__ import annotations

from app.channels.ports import ChannelAccountResolver
from app.channels.types import ChannelAccountRef


class ChannelAccountStatus:
    """Lifecycle status for a channel account.

    Plain string constants (not an enum) so they match the Alembic CHECK
    constraint verbatim and so future statuses can be added without a
    migration of this contract layer.
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class InMemoryAccountResolver(ChannelAccountResolver):
    """Test-only resolver backed by a dict keyed by ``(provider, account_key)``.

    Production resolves authority from the ``ChannelAccount`` table (Phase 2).
    This double lets the conformance suite exercise active/inactive behavior
    without a database. It deliberately does **not** enforce the one-active-
    Messenger rule — that is a persistence-layer invariant, not a resolver one.
    """

    def __init__(self) -> None:
        self._accounts: dict[tuple[str, str], ChannelAccountRef] = {}

    def upsert(self, account: ChannelAccountRef) -> None:
        """Insert or replace the ref for ``(provider, account_key)``."""
        self._accounts[(account.provider, account.account_key)] = account

    def remove(self, *, provider: str, account_key: str) -> None:
        self._accounts.pop((provider, account_key), None)

    async def resolve_active(
        self, *, provider: str, account_key: str
    ) -> ChannelAccountRef | None:
        ref = self._accounts.get((provider, account_key))
        if ref is None or not ref.is_active:
            return None
        return ref

    async def resolve_any(
        self, *, provider: str, account_key: str
    ) -> ChannelAccountRef | None:
        return self._accounts.get((provider, account_key))


__all__ = ["ChannelAccountStatus", "InMemoryAccountResolver"]
