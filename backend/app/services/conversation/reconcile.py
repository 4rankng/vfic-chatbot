"""Reconcile sweeps for the bot path.

Resolves rows a crashed turn left behind: the ephemeral PENDING placeholder
becomes FAILED, and a stale SENDING row becomes the terminal SEND_UNKNOWN
(at-most-once — never automatically retried). Mixed into
``BotConversationState``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update

from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.services.conversation._shared import utcnow


class ReconcileMixin:
    """Recovery sweeps over rows a crashed turn left unresolved."""

    async def mark_stale_pending_failed(self, conv_id: uuid.UUID) -> int:
        """Flip any BOT/PENDING message rows for this conversation to FAILED.

        Call ONLY after ``acquire_lock()`` succeeded, so no live turn owns these
        rows.  Returns the number of rows updated.  No version bump, no
        ``last_outbound_at`` change, no events — the PENDING placeholder is
        ephemeral UI chrome that a crashed turn left behind.
        """
        res = await self.db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.BOT,
                Message.delivery_status == DeliveryStatus.PENDING,
            )
            .values(delivery_status=DeliveryStatus.FAILED)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return res.rowcount

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
        if res.rowcount:
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
        return res.rowcount
