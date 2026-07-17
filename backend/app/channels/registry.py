"""Provider adapter registry.

Business logic resolves an adapter by provider id through
:class:`ChannelAdapterRegistry`; it never imports a concrete adapter class or
branches on a provider string. The registry **fails closed**: an unknown or
unregistered provider yields ``None`` from :meth:`get`, which the caller
translates into a safe "not connected" outcome — never an exception that could
leak provider internals.

Capabilities are queried through typed ``get_*`` accessors returning
``Optional[Protocol]``. Callers check for ``None`` rather than using
``hasattr``; "no capability" is a legitimate state (e.g. Zalo OA has no typing
endpoint) and means "do nothing", not "failure".

Phase 1 ships the registry empty in production (no provider is registered
until Phase 3 preserves Zalo behavior through it). The conformance suite
registers a test-only fake adapter.
"""

from __future__ import annotations

from typing import Iterable

from app.channels.ports import ReceiptCapability, TextChannelAdapter, TypingCapability
from app.channels.types import is_known_provider


class ChannelAdapterRegistry:
    """Maps provider id → adapter instance, with typed capability lookup.

    The registry is the single place that knows which concrete adapters are
    installed. Services depend on this class (or its Protocol) and never on a
    provider module.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, TextChannelAdapter] = {}

    def register(self, adapter: TextChannelAdapter) -> None:
        """Register an adapter under its ``provider`` id.

        Re-registering a provider replaces the prior adapter (useful in tests).
        The provider id must be one of the installed providers to prevent typos
        selecting a non-existent future provider.
        """
        provider = getattr(adapter, "provider", "")
        if not is_known_provider(provider):
            raise ValueError(f"unknown provider id: {provider!r}")
        self._adapters[provider] = adapter

    def providers(self) -> Iterable[str]:
        """Read-only view of registered provider ids."""
        return tuple(self._adapters.keys())

    def get(self, provider: str) -> TextChannelAdapter | None:
        """Return the text adapter, or ``None`` if not registered/unknown.

        ``None`` is the fail-closed signal: the caller must not send. It is
        never raised — business logic translates it into a safe outcome.
        """
        return self._adapters.get(provider)

    def get_typing(self, provider: str) -> TypingCapability | None:
        """Return the typing capability, or ``None`` if absent/unregistered.

        Absence means "no typing indicator" (Zalo OA, Messenger), not an error.
        """
        adapter = self._adapters.get(provider)
        if adapter is None:
            return None
        return adapter if isinstance(adapter, TypingCapability) else None

    def get_receipt(self, provider: str) -> ReceiptCapability | None:
        """Return the receipt capability, or ``None`` if absent/unregistered."""
        adapter = self._adapters.get(provider)
        if adapter is None:
            return None
        return adapter if isinstance(adapter, ReceiptCapability) else None


__all__ = ["ChannelAdapterRegistry"]
