"""Transport-neutral inbound-message command and application orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class InboundIdentity:
    provider: str
    account_key: str
    external_id: str


@dataclass(frozen=True, slots=True)
class InboundTextCommand:
    identity: InboundIdentity
    external_message_id: str
    text: str


@dataclass(frozen=True, slots=True)
class InboundIngressResult:
    status: Literal["persisted", "duplicate", "ignored"]
    conversation_id: str | None = None
    dedup_key: str | None = None


def inbound_dedup_key(command: InboundTextCommand) -> str:
    raw = (
        f"{command.identity.provider}:{command.identity.account_key}:"
        f"{command.identity.external_id}:{command.external_message_id}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class InboundMessagePort(Protocol):
    async def claim(self, command: InboundTextCommand, dedup_key: str) -> bool: ...

    async def persist(self, command: InboundTextCommand) -> str | None:
        """Return the conversation id, or None when durable uniqueness wins."""
        ...


class InboundMessageUseCases:
    """Own dedup-before-persist order independently of provider and database."""

    def __init__(self, port: InboundMessagePort) -> None:
        self._port = port

    async def ingest(self, command: InboundTextCommand) -> InboundIngressResult:
        dedup_key = inbound_dedup_key(command)
        if not await self._port.claim(command, dedup_key):
            return InboundIngressResult(status="duplicate", dedup_key=dedup_key)
        conversation_id = await self._port.persist(command)
        if conversation_id is None:
            return InboundIngressResult(status="duplicate", dedup_key=dedup_key)
        return InboundIngressResult(
            status="persisted",
            conversation_id=conversation_id,
            dedup_key=dedup_key,
        )


__all__ = [
    "InboundIdentity",
    "InboundIngressResult",
    "InboundMessagePort",
    "InboundMessageUseCases",
    "InboundTextCommand",
    "inbound_dedup_key",
]
