"""Provider-facing adapter for neutral message ingress."""

from __future__ import annotations

from app.channels import types as ct
from app.conversation_messaging.application.ingress import (
    InboundIdentity,
    InboundIngressResult,
    InboundMessageUseCases,
    InboundTextCommand,
)
from app.conversation_messaging.infrastructure.ingress import (
    SqlAlchemyInboundMessageAdapter,
)

def _command(message: ct.ChannelInboundMessage) -> InboundTextCommand:
    return InboundTextCommand(
        identity=InboundIdentity(
            provider=message.identity.provider,
            account_key=message.identity.account_key,
            external_id=message.identity.external_id,
        ),
        external_message_id=message.external_message_id,
        text=message.text,
        attribution=message.attribution,
    )


class ChannelIngressService:
    """Translate provider values and delegate to the messaging use case."""

    def __init__(self, db) -> None:
        self._use_cases = InboundMessageUseCases(SqlAlchemyInboundMessageAdapter(db))

    async def ingest(self, message: ct.ChannelInboundMessage) -> InboundIngressResult:
        return await self._use_cases.ingest(_command(message))


__all__ = ["ChannelIngressService"]
