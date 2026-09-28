"""Reconcile sweeps for rows a crashed turn left behind.

Resolves a stale BOT/SENDING message (and its still-SENDING outbox command) to
the terminal unknown state. Mixed into ``BotConversationState``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

from sqlalchemy import select, update

from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.services.conversation._shared import affected_rows, utcnow



if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

class ReconcileMixin:
    """Crash-window sweeps for the bot-send path."""

    # Assigned by the composing state class. Declared so ``self.db``
    # resolves here — the mixin reads it but never owns it.
    db: AsyncSession

    async def resolve_unconfirmed_sending(self, conv_id: uuid.UUID) -> int:
        """Resolve a stale BOT/SENDING row as ``SEND_UNKNOWN``.

        A worker crash can happen either before or after Zalo accepts the POST.
        Retrying might duplicate the candidate-visible message, while declaring it
        sent would be false when the crash happened before the POST.  The terminal
        unknown state preserves that distinction and is never automatically retried.
        """
        res = await self.db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.BOT,
                Message.delivery_status == DeliveryStatus.SENDING,
            )
            .values(delivery_status=DeliveryStatus.SEND_UNKNOWN)
            .execution_options(synchronize_session=False)
        )
        if affected_rows(res):
            from app.models.outbox import OutboxStatus, OutboundOutbox

            await self.db.execute(
                update(OutboundOutbox)
                .where(
                    OutboundOutbox.message_id.in_(
                        select(Message.id).where(
                            Message.conversation_id == conv_id,
                            Message.sender == MessageSender.BOT,
                            Message.delivery_status == DeliveryStatus.SEND_UNKNOWN,
                        )
                    ),
                    OutboundOutbox.status == OutboxStatus.SENDING.value,
                )
                .values(status=OutboxStatus.SEND_UNKNOWN.value, updated_at=utcnow())
                .execution_options(synchronize_session=False)
            )
        await self.db.commit()
        return affected_rows(res)
