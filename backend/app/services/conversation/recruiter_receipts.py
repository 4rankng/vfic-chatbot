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

from typing import TYPE_CHECKING
from sqlalchemy import select

from app.conversation_messaging.application.ports import DeliveryResultPort
from app.conversation_messaging.domain.delivery import receipt_advances
from app.models.conversation import (
    Conversation,
    ConversationMode,
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
from app.services.tingting_api import TingtingVerifyAttemptsStore
from app.shared.application.outbound import PARTIAL_DELIVERY_ERROR_PREFIX



if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.conversation_messaging.application.ports import ConversationEventsPort

class RecruiterReceiptsMixin:
    """Human replies, their delivery finalization, and Zalo delivery receipts.

    Needs only the ``db``/``events`` pair ``RecruiterMessagingState`` already
    holds; no dependency back on the lifecycle transitions.
    """

    # Assigned by the composing state class. Declared so ``self.db``
    # resolves here — the mixin reads it but never owns it.
    db: AsyncSession
    events: ConversationEventsPort

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
        # Operator rule 2026-09-28: a consultant's reply demotes HUMAN to
        # SEMI_AUTO — the thread stays theirs for _SEMI_AUTO_INACTIVITY
        # (30 minutes since this message), then the bot answers new inbound
        # again without a manual release.
        if conv.mode == ConversationMode.HUMAN:
            conv.mode = ConversationMode.SEMI_AUTO
            conv.needs_human = False
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
        # A human has replied: the identity-verification attempt cap re-arms
        # (only a human message resets it). Best-effort Redis, fail-open.
        await TingtingVerifyAttemptsStore().reset(str(conv.id))
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
        # Operator rule 2026-09-28: a consultant's reply demotes HUMAN to
        # SEMI_AUTO — the thread stays theirs for _SEMI_AUTO_INACTIVITY
        # (30 minutes since this message), then the bot answers new inbound
        # again without a manual release.
        if conv.mode == ConversationMode.HUMAN:
            conv.mode = ConversationMode.SEMI_AUTO
            conv.needs_human = False
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
        # A human has replied: the identity-verification attempt cap re-arms
        # (only a human message resets it). Best-effort Redis, fail-open.
        await TingtingVerifyAttemptsStore().reset(str(conv.id))
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

        Receipts prove delivery only for their exact stored provider message
        ids. An id-less SEND_UNKNOWN row cannot be correlated, so it stays
        uncertain for review. A receipt for another message in the conversation
        must not fabricate confirmation for that row.

        Each moved message emits ``message_created`` (in addition to the single
        ``conversation_updated``) so the recruiter console's per-message delivery
        badge refreshes in realtime — the frontend message store updates
        ``delivery_status`` only via ``message.created`` events.

        Partial logical answers retain SEND_UNKNOWN even when an accepted
        prefix has a receipt: that receipt says nothing about the unsent tail.
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
            if (msg.external_error or "").startswith(PARTIAL_DELIVERY_ERROR_PREFIX):
                continue
            if receipt_advances(msg.delivery_status, target):
                msg.delivery_status = target
                moved.append(msg)
        if moved:
            await self.db.commit()
            for msg in moved:
                await self.events.message_created(msg, conv)
            await self.events.conversation_updated(conv)
        return len(moved)
