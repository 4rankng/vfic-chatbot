"""SQLAlchemy/provider compatibility adapter for durable outbound recovery."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SqlAlchemyOutboundRecoveryAdapter:
    """Bind the recovery use case to existing transactional adapters."""

    def __init__(self, *, session_factory, stale_after_seconds: int) -> None:
        self._session_factory = session_factory
        self.stale_after_seconds = stale_after_seconds

    async def pending_ids(self) -> list[int]:
        from app.services.outbox_service import pending_outbox_ids

        async with self._session_factory() as db:
            return await pending_outbox_ids(db)

    async def stale_sending_ids(self) -> list[int]:
        from app.services.outbox_service import stale_sending_outbox_ids

        async with self._session_factory() as db:
            return await stale_sending_outbox_ids(
                db,
                stale_after_seconds=self.stale_after_seconds,
            )

    async def dispatch_pending(self, outbox_id: int) -> bool:
        from app.services.outbox_service import dispatch_outbox

        return await self._finalize_result(
            dispatch=lambda db: dispatch_outbox(db, outbox_id=outbox_id),
        )

    async def terminalize_stale_sending(self, outbox_id: int) -> bool:
        from app.services.outbox_service import (
            DispatchResult,
            claim_stale_sending_unknown,
        )

        async def terminalize(db):
            stale = await claim_stale_sending_unknown(
                db,
                outbox_id=outbox_id,
                stale_after_seconds=self.stale_after_seconds,
            )
            if stale is None:
                return None
            return DispatchResult(
                outbox_id=stale.outbox_id,
                message_id=stale.message_id,
                ok=False,
                error="outbound dispatch interrupted before receipt",
                error_class="unknown",
            )

        return await self._finalize_result(dispatch=terminalize)

    async def _finalize_result(self, *, dispatch) -> bool:
        from app.models.conversation import Conversation, Message
        from app.services.conversation import ConversationService

        async with self._session_factory() as db:
            result = await dispatch(db)
            if result is None:
                return False

            msg = await db.get(Message, result.message_id)
            if msg is None:
                logger.warning(
                    "outbound dispatcher: missing message id=%s",
                    result.message_id,
                )
                return False
            conv = await db.get(Conversation, msg.conversation_id)
            if conv is None:
                logger.warning(
                    "outbound dispatcher: missing conversation for message=%s",
                    msg.id,
                )
                return False
            await ConversationService(db).finalize_outbound_dispatch(
                conv,
                message_id=result.message_id,
                outbox_id=result.outbox_id,
                delivered=result.ok,
                zalo_message_id=result.zalo_message_id,
                external_error=result.error,
                error_class=result.error_class,
                suppressed=result.suppressed,
                telemetry=result.telemetry,
            )
            return True


__all__ = ["SqlAlchemyOutboundRecoveryAdapter"]
