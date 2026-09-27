"""Recruiter replies and their delivery receipts.

The messaging/receipt half of ``recruiter_path.py``: a human reply (persist →
dispatch → finalize), the retry of a definite delivery failure, and the Zalo
receipts that advance an outbound message's ``delivery_status``. Mixed into
:class:`~app.services.conversation.recruiter_path.RecruiterMessagingState`, so
the lifecycle transitions stay beside the replies they authorize while this
change reason gets its own module — the same decomposition
``bot_path.py`` already applies to the bot-send half.

Delivery finalization is the shared outbox seam: the reply row is written
PENDING, the command is dispatched through ``outbound_outbox``, and the row is
then stamped from the attempt's real outcome. Never the other way round.
"""

from __future__ import annotations

from sqlalchemy import select

from app.conversation_messaging.application.ports import DeliveryResultPort
from app.conversation_messaging.domain.delivery import receipt_advances
from app.models.conversation import (
    Conversation,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.conversation._shared import (
    _delivery_status_for_send_error,
    utcnow,
)
from app.services.conversation.unreachable import (
    USER_UNREACHABLE_SEND_CLASS,
    apply_user_unreachable_side_effects,
)


class RecruiterReceiptsMixin:
    """Human replies, their delivery finalization, and Zalo delivery receipts.

    Needs only the ``db``/``events`` pair ``RecruiterMessagingState`` already
    holds; no dependency back on the lifecycle transitions.
    """

    async def record_recruiter_message(
        self, conv: Conversation, recruiter: User, body: str, result: DeliveryResultPort
    ) -> Message:
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.RECRUITER,
            recruiter_id=recruiter.id,
            body=body,
            delivery_status=DeliveryStatus.SENT if result.ok else DeliveryStatus.FAILED,
            zalo_message_id=result.msg_id,
            external_error=None if result.ok else result.error,
        )
        self.db.add(msg)
        if result.ok:
            conv.last_outbound_at = utcnow()
        conv.taken_over_at = utcnow()
        conv.version += 1
        conv.conversation_seq += 1
        await record_audit(
            self.db,
            action="send_recruiter_message",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"message_id": None, "delivered": result.ok},
        )
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def prepare_recruiter_message(
        self,
        conv: Conversation,
        recruiter: User,
        *,
        body: str,
        channel: str,
        payload: dict,
    ) -> tuple[Message, int]:
        """Commit one recruiter message and its PENDING command before sending.

        A retry reuses this message/outbox pair; this method is intentionally
        called only for a new human reply, never for a provider retry.
        """
        from app.services.outbox_service import create_pending_outbox

        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.RECRUITER,
            recruiter_id=recruiter.id,
            body=body,
            delivery_status=DeliveryStatus.PENDING,
        )
        self.db.add(msg)
        await self.db.flush()
        outbox = await create_pending_outbox(
            self.db,
            message_id=msg.id,
            channel=channel,
            payload=payload,
        )
        conv.taken_over_at = utcnow()
        conv.version += 1
        conv.conversation_seq += 1
        await record_audit(
            self.db,
            action="send_recruiter_message",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"message_id": msg.id, "delivered": False},
        )
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = 0
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg, outbox.id

    async def finalize_recruiter_delivery(
        self,
        conv: Conversation,
        *,
        message_id: int,
        outbox_id: int,
        delivered: bool,
        zalo_message_id: str | None = None,
        external_error: str | None = None,
        error_class: str | None = None,
        suppressed: bool = False,
    ) -> Message:
        """Finalize one persisted recruiter command without creating a bubble."""
        from app.models.outbox import OutboxStatus, OutboundOutbox

        msg = await self.db.get(Message, message_id)
        outbox = await self.db.get(OutboundOutbox, outbox_id)
        if msg is None or msg.conversation_id != conv.id or outbox is None:
            raise RuntimeError("outbound message disappeared before delivery finalization")
        delivery_status = (
            DeliveryStatus.SUPPRESSED
            if suppressed
            else _delivery_status_for_send_error(error_class, ok=delivered)
        )
        if delivery_status is None:
            delivery_status = DeliveryStatus.SENT if delivered else DeliveryStatus.FAILED
        msg.delivery_status = delivery_status
        msg.zalo_message_id = zalo_message_id
        msg.provider_message_id = zalo_message_id
        msg.external_error = None if delivered else external_error
        outbox.status = (
            OutboxStatus.SUPPRESSED.value
            if suppressed
            else OutboxStatus.SENT.value
            if delivered
            else OutboxStatus.SEND_UNKNOWN.value
            if delivery_status == DeliveryStatus.SEND_UNKNOWN
            else OutboxStatus.FAILED.value
        )
        outbox.zalo_message_id = zalo_message_id
        outbox.provider_message_id = zalo_message_id
        outbox.last_error = None if delivered else external_error
        outbox.updated_at = utcnow()
        if delivered:
            outbox.sent_at = utcnow()
            conv.last_outbound_at = utcnow()
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox.attempts
        if error_class == USER_UNREACHABLE_SEND_CLASS:
            await apply_user_unreachable_side_effects(self.db, conv, self.events)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def retry_recruiter_message(self, conv: Conversation, *, message_id: int) -> int | None:
        """Make an existing definite failure dispatchable again, without a new message."""
        from app.models.outbox import OutboxStatus, OutboundOutbox

        msg = await self.db.get(Message, message_id)
        if (
            msg is None
            or msg.conversation_id != conv.id
            or msg.sender != MessageSender.RECRUITER
            or msg.delivery_status != DeliveryStatus.FAILED
        ):
            return None
        outbox = await self.db.scalar(
            select(OutboundOutbox).where(OutboundOutbox.message_id == message_id)
        )
        if outbox is None or outbox.status != OutboxStatus.FAILED.value:
            return None
        outbox.status = OutboxStatus.PENDING.value
        outbox.last_error = None
        outbox.updated_at = utcnow()
        msg.delivery_status = DeliveryStatus.PENDING
        msg.external_error = None
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox.attempts
        await self.events.message_created(msg, conv)
        return outbox.id

    # --- OA webhook side events (receipts) ---

    async def apply_delivery_receipt(
        self,
        conv: Conversation,
        *,
        zalo_message_id: str | None,
        delivered: bool = False,
        seen: bool = False,
    ) -> bool:
        """Advance an outbound message's delivery_status from a Zalo receipt.

        Forward-only (READ > DELIVERED > SENT); never regresses and never touches
        ``version`` or ``unread_count`` — a receipt must not invalidate an
        in-flight bot turn's optimistic-lock recheck. Returns whether a row moved.
        """
        moved = await self.apply_delivery_receipt_batch(
            conv,
            zalo_message_ids=[zalo_message_id] if zalo_message_id else [],
            delivered=delivered,
            seen=seen,
        )
        return moved > 0

    async def apply_delivery_receipt_batch(
        self,
        conv: Conversation,
        *,
        zalo_message_ids: list[str],
        delivered: bool = False,
        seen: bool = False,
    ) -> int:
        """Advance delivery_status for multiple outbound messages in one pass.

        ``user_seen_message`` carries an array of message ids (a user can see
        several messages at once); this advances every matched Message row with a
        single commit + a single realtime emit. Forward-only, no ``version`` or
        ``unread_count`` touch (see :meth:`apply_delivery_receipt`). Returns the
        number of rows that moved.

        SEND_UNKNOWN fallback: a message stamped SEND_UNKNOWN (transport timeout,
        stale SENDING, interrupted dispatch) carries NO ``zalo_message_id`` — the
        send failed before Zalo returned one. It therefore can never be matched by
        the ``zalo_message_id IN (ids)`` query above, so a later ``user_seen``
        receipt proving the user actually saw it leaves the row stuck at
        SEND_UNKNOWN forever (recruiter console shows "Chưa xác nhận gửi" despite
        confirmed delivery). A Zalo receipt only fires for a message that exists
        on Zalo's side, so its arrival is ground-truth proof the SEND_UNKNOWN row
        reached Zalo. Advance any id-less SEND_UNKNOWN outbound row in this
        conversation to the target status. Strictly scoped to SEND_UNKNOWN so a
        PENDING placeholder, a known FAILED, or a SUPPRESSED row is never revived.

        Each moved message emits ``message_created`` (in addition to the single
        ``conversation_updated``) so the recruiter console's per-message delivery
        badge refreshes in realtime — the frontend message store updates
        ``delivery_status`` only via ``message.created`` events.
        """
        ids = [mid for mid in zalo_message_ids if mid]
        if not ids:
            return 0
        if seen:
            target = DeliveryStatus.READ
        elif delivered:
            target = DeliveryStatus.DELIVERED
        else:
            return 0
        result = await self.db.scalars(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.zalo_message_id.in_(ids),
                Message.sender.in_([MessageSender.BOT, MessageSender.RECRUITER]),
            )
        )
        moved: list[Message] = []
        for msg in result.all():
            if receipt_advances(msg.delivery_status, target):
                msg.delivery_status = target
                moved.append(msg)
        if receipt_advances(DeliveryStatus.SEND_UNKNOWN, target):
            # Id-less SEND_UNKNOWN rows can never match the query above. They are
            # disjoint from the id-matched set (a row cannot have both a non-null
            # id-in-ids and a NULL id), so no message is double-counted here.
            unresolved = await self.db.scalars(
                select(Message).where(
                    Message.conversation_id == conv.id,
                    Message.zalo_message_id.is_(None),
                    Message.delivery_status == DeliveryStatus.SEND_UNKNOWN,
                    Message.sender.in_([MessageSender.BOT, MessageSender.RECRUITER]),
                )
            )
            for msg in unresolved.all():
                msg.delivery_status = target
                moved.append(msg)
        if moved:
            await self.db.commit()
            for msg in moved:
                await self.events.message_created(msg, conv)
            await self.events.conversation_updated(conv)
        return len(moved)
