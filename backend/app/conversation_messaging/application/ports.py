"""Provider-neutral ports owned by conversation and messaging use cases."""

from __future__ import annotations

from typing import Any, Protocol

from app.shared.application.outbound import OutboundTelemetry


class DeliveryResultPort(Protocol):
    """Provider-neutral delivery result consumed by messaging orchestration."""

    @property
    def ok(self) -> bool: ...

    @property
    def msg_id(self) -> str | None: ...

    @property
    def error(self) -> str | None: ...

    @property
    def error_class(self) -> str | None: ...

    @property
    def telemetry(self) -> OutboundTelemetry | None: ...


class ConversationEventsPort(Protocol):
    """Publish committed conversation state without exposing Socket.IO/Redis."""

    async def conversation_updated(self, conversation: Any) -> None: ...

    async def message_created(self, message: Any, conversation: Any) -> None: ...

    def schedule_realtime(self, message: Any, conversation: Any) -> None: ...


class BotTurnQueuePort(Protocol):
    """Stable queue boundary for one already-persisted inbound command."""

    def enqueue(self, payload: dict[str, Any]) -> bool: ...


__all__ = ["BotTurnQueuePort", "ConversationEventsPort", "DeliveryResultPort"]
