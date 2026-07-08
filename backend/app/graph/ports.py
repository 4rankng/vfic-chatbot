"""Typed ports (dependency-injection interfaces) for the graph layer.

The agent brain must not import concrete service classes — that coupling is what
made the layer un-testable in isolation and created the latent graph ↔ services
import edge. Instead the brain depends on these Protocols; the composition root
(:func:`app.graph.factories.build_deps`) constructs the concrete services and
injects them via :class:`~app.graph.types.GraphDeps`.

Ports are intentionally loose-typed (``Any`` for domain objects): they describe
*what the brain calls*, not the full service surface, so the concrete service can
evolve without dragging the contract along.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SendOutcome:
    """Graph-local send result (mirrors the service-layer ``SendResult`` shape).

    The proactive turn constructs synthetic outcomes for non-send paths (the agent
    decided not to send, safety blocked, generation threw). Defining the shape here
    keeps the graph layer from importing the Zalo service module. Downstream
    persistence reads only ``ok`` / ``msg_id`` / ``error``, so this satisfies the
    service contract structurally.
    """

    ok: bool
    msg_id: str | None = None
    error: str | None = None


class ConversationStatePort(Protocol):
    async def record_proactive_outcome(
        self, conv: Any, *, message: str, result: Any
    ) -> Any: ...

    async def release_lock(self, conv: Any) -> None: ...


class ConversationPort(Protocol):
    """Subset of the conversation service surface the brain depends on."""

    state: ConversationStatePort

    async def get(self, conversation_id: Any) -> Any: ...

    async def last_messages(self, conv: Any, *, limit: int) -> list[Any]: ...

    async def record_bot_pending(self, conv: Any) -> Any: ...

    async def record_bot_outcome(
        self,
        conv: Any,
        *,
        version_at_start: int,
        reply: str,
        started_at: Any,
        sent: bool,
        pending_message_id: int | None,
        external_error: str | None = None,
        zalo_message_id: str | None = None,
    ) -> None: ...

    async def recheck_ownership(self, conv: Any, version_at_start: int) -> bool: ...

    async def acquire_lock(self, conv_id: Any) -> bool: ...


__all__ = ["SendOutcome", "ConversationPort", "ConversationStatePort"]
