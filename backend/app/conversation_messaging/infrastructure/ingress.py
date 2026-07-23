"""SQLAlchemy adapter for provider-neutral inbound messages."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.conversation_messaging.application.ingress import (
    InboundTextCommand,
    PersistedInboundMessage,
)

_MESSAGE_PROVIDER_ID_UNIQUE_CONSTRAINT = "uq_messages_conv_provider_message"


def _is_duplicate_message_integrity_error(error: IntegrityError) -> bool:
    sqlstate: str | None = None
    constraint_name: str | None = None
    current: BaseException | None = error.orig
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        sqlstate = sqlstate or getattr(current, "sqlstate", None)
        constraint_name = constraint_name or getattr(current, "constraint_name", None)
        current = current.__cause__ or current.__context__
    return (
        sqlstate == "23505"
        and constraint_name == _MESSAGE_PROVIDER_ID_UNIQUE_CONSTRAINT
    )


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

    async def persist(self, command: InboundTextCommand) -> PersistedInboundMessage | None:
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
            message = await service.record_inbound(
                conversation,
                body=command.text,
                provider_message_id=command.external_message_id,
                runtime_revision_id=None,
                authority_generation=None,
                runtime_fingerprint=None,
            )
        except IntegrityError as exc:
            await self._db.rollback()
            if not _is_duplicate_message_integrity_error(exc):
                raise
            # A racing delivery won the exact durable message-id uniqueness
            # constraint after the transient claim.
            return None
        return PersistedInboundMessage(
            conversation_id=str(conversation.id),
            message_id=message.id,
            body=message.body,
            provider_message_id=message.provider_message_id or "",
            created_at=message.created_at,
        )


__all__ = ["SqlAlchemyInboundMessageAdapter"]
