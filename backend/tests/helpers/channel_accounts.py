"""In-memory ChannelAccountResolver double for the channel conformance suite.

Production resolves authority from the ``ChannelAccount`` table; this double
lets the conformance and dispatch tests exercise active/inactive resolver
behavior without a database. It deliberately does **not** enforce the
one-active-Messenger rule — that is a persistence-layer invariant, not a
resolver one.
"""

from __future__ import annotations

from app.channels.ports import ChannelAccountResolver
from app.channels.types import ChannelAccountRef


class InMemoryAccountResolver(ChannelAccountResolver):
    """Test-only resolver double backed by a dict keyed by ``(provider, account_key)``."""

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
