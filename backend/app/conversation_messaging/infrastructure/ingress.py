"""SQLAlchemy compatibility adapter for neutral inbound messages."""

from __future__ import annotations

from app.conversation_messaging.application.ingress import InboundTextCommand


class SqlAlchemyInboundMessageAdapter:
    def __init__(self, db) -> None:
        self._db = db

    async def claim(self, command: InboundTextCommand, dedup_key: str) -> bool:
        from app.services.dedup import MessageDedupService

        identity = command.identity
        return await MessageDedupService.claim(
            self._db,
            f"{identity.provider}:{identity.account_key}:{identity.external_id}",
            dedup_key,
        )

    async def persist(self, command: InboundTextCommand) -> str | None:
        from app.services.conversation import ConversationService

        identity = command.identity
        if identity.provider == "zalo_bot":
            channel_alias = "bot"
        elif identity.provider == "zalo_oa":
            channel_alias = "oa"
        else:
            channel_alias = identity.provider

        service = ConversationService(self._db)
        conversation = await service.ensure_by_identity(
            provider=identity.provider,
            account_key=identity.account_key,
            external_id=identity.external_id,
            zalo_chat_id_alias=None,
            zalo_channel_alias=channel_alias,
        )
        await self._db.refresh(conversation)
        try:
            await service.record_inbound(
                conversation,
                body=command.text,
                provider_message_id=command.external_message_id,
                runtime_revision_id=None,
                authority_generation=None,
                runtime_fingerprint=None,
            )
        except Exception:
            # Preserve the compatibility facade's durable-uniqueness behavior:
            # a late duplicate (or post-commit publish failure) is acknowledged.
            await self._db.rollback()
            return None
        return str(conversation.id)


__all__ = ["SqlAlchemyInboundMessageAdapter"]
