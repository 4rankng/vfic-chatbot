"""Conversation state mutations + orchestration (the takeover race-guard core).

All state changes bump ``version`` (the optimistic-lock token) and fan out a realtime
event via the event bus.

Reads live in ``repository.py``; realtime publishing in ``events.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text, update

from app.core.config import PROACTIVE_OPTOUT_PHRASES, get_settings
from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.zalo_bot_service import SendResult

_settings = get_settings()
_SEMI_AUTO_INACTIVITY = timedelta(minutes=5)

logger = logging.getLogger(__name__)

# Forward-only delivery progression for receipt handling (READ > DELIVERED > SENT).
# PENDING/FAILED/SUPPRESSED sit at 0 so a receipt never revives a non-sent row.
_DELIVERY_RANK = {
    DeliveryStatus.PENDING: 0,
    DeliveryStatus.FAILED: 0,
    DeliveryStatus.SUPPRESSED: 0,
    DeliveryStatus.SENT: 1,
    DeliveryStatus.DELIVERED: 2,
    DeliveryStatus.READ: 3,
}


class ConversationConflict(Exception):
    """Raised when a recruiter tries to take over a conversation owned by another."""

    def __init__(self, message: str = "", owner_name: str | None = None) -> None:
        super().__init__(message)
        self.owner_name = owner_name


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _fetch_owner_name(db, conv: Conversation) -> str | None:
    """Look up the full name of the current owner of *conv*.

    Used by :meth:`take_over` and :meth:`semi_auto` when a conditional
    UPDATE fails, to produce a rich ``ConversationConflict`` message.
    """
    from sqlalchemy import select

    from app.models.user import User as UserModel

    owner_row = await db.scalar(
        select(UserModel.full_name).where(UserModel.id == conv.assigned_recruiter_id)
    )
    return owner_row or None


class ConversationState:
    """Mutates conversation/message rows + records audit + publishes realtime events.

    Composes a ``ConversationRepository`` (for reads within mutations) and a
    ``ConversationEventBus`` (for publishing). Pure orchestration — no new business
    rules.
    """

    def __init__(self, db, repo, events) -> None:
        self.db = db
        self.repo = repo
        self.events = events

    # --- webhook-side primitives (used by US-006 chatbot) ---
    async def ensure(self, zalo_chat_id: str, *, zalo_channel: str = "bot") -> Conversation:
        conv = await self.repo.get_by_zalo(zalo_chat_id)
        if conv is None:
            conv = Conversation(zalo_chat_id=zalo_chat_id, zalo_channel=zalo_channel)
            self.db.add(conv)
            await self.db.flush()
        elif not getattr(conv, "zalo_channel", None):
            conv.zalo_channel = zalo_channel
            await self.db.flush()
        return conv

    def semi_auto_inactive(self, conv: Conversation) -> bool:
        reference = conv.taken_over_at or conv.updated_at
        if reference is None:
            return True
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        return utcnow() - reference >= _SEMI_AUTO_INACTIVITY

    def run_start_guard(self, conv: Conversation) -> bool:
        """True only when the bot may run.

        BOT is always eligible. SEMI_AUTO is eligible after the assigned human has
        been inactive for five minutes. HUMAN/CLOSED starve the bot.
        """
        if conv.mode == ConversationMode.BOT:
            return True
        if conv.mode == ConversationMode.SEMI_AUTO:
            return self.semi_auto_inactive(conv)
        return False

    async def record_inbound(
        self,
        conv: Conversation,
        *,
        body: str,
        zalo_message_id: str | None = None,
    ) -> Message:
        """Persist an inbound worker message and update conversation attention state."""
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.WORKER,
            body=body,
            zalo_message_id=zalo_message_id,
        )
        self.db.add(msg)
        conv.last_inbound_at = utcnow()
        # Proactive opt-out: cheap substring scan on the hot path. Accepted
        # tradeoff (A7) — atomicity with the inbound txn outweighs purity.
        _lower = body.strip().lower()
        if _lower and any(p in _lower for p in PROACTIVE_OPTOUT_PHRASES):
            conv.followup_opted_out = True
            logger.info(
                "proactive opt-out: conversation=%s phrase detected",
                conv.zalo_chat_id,
            )
        if conv.mode != ConversationMode.BOT:
            conv.unread_count = (conv.unread_count or 0) + 1
        conv.version += 1
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def acquire_lock(self, conv_id: uuid.UUID, ttl_seconds: int | None = None) -> bool:
        """Per-chat mutex via bot_locked_until. Atomic: only one run holds it at a time.

        TTL defaults to settings.bot_lock_ttl_seconds, which is sized to exceed the
        worst-case single turn (a worker crash mid-turn is recovered by TTL expiry;
        the `version` optimistic token in recheck_ownership is the real guard
        against a stale run sending after a takeover).
        """
        ttl = ttl_seconds if ttl_seconds is not None else _settings.bot_lock_ttl_seconds
        locked_until = utcnow() + timedelta(seconds=ttl)
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv_id,
                or_(
                    Conversation.bot_locked_until.is_(None),
                    Conversation.bot_locked_until < utcnow(),
                ),
            )
            .values(bot_locked_until=locked_until)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return res.rowcount == 1

    async def release_lock(self, conv: Conversation) -> None:
        conv.bot_locked_until = None
        await self.db.commit()

    async def recheck_ownership(self, conv: Conversation, version_at_start: int) -> bool:
        """Pre-send guard: bot may send only if eligible and version unchanged.

        IMPORTANT: the caller **must** run ``db.refresh(conv)`` immediately
        before calling this method (``expire_on_commit=False`` means the
        identity map hides concurrent takeovers).  Failing to refresh reads a
        stale in-memory ``version`` and may approve a send after a takeover.
        """
        return self.run_start_guard(conv) and conv.version == version_at_start

    async def record_bot_outcome(
        self,
        conv: Conversation,
        *,
        version_at_start: int,
        reply: str,
        started_at: datetime,
        sent: bool,
        pending_message_id: int | None = None,
        external_error: str | None = None,
        zalo_message_id: str | None = None,
    ) -> Message:
        """Log a bot_run + BOT message; clears the lock.

        ``sent=False`` means either ownership suppression or delivery failure.
        ``external_error`` disambiguates real send failures so recovery can
        retry them instead of treating them as completed suppressed turns.
        """
        outcome = (
            BotRunOutcome.ERROR
            if external_error
            else BotRunOutcome.SENT if sent else BotRunOutcome.SUPPRESSED
        )
        delivery_status = (
            DeliveryStatus.FAILED
            if external_error
            else DeliveryStatus.SENT if sent else DeliveryStatus.SUPPRESSED
        )
        run = BotRun(
            conversation_id=conv.id,
            version_at_start=version_at_start,
            proposed_reply=reply,
            outcome=outcome,
            started_at=started_at,
            ended_at=utcnow(),
        )
        self.db.add(run)
        await self.db.flush()
        msg = None
        if pending_message_id is not None:
            pending_msg = await self.db.get(Message, pending_message_id)
            if (
                pending_msg is not None
                and pending_msg.conversation_id == conv.id
                and pending_msg.sender == MessageSender.BOT
                and pending_msg.delivery_status == DeliveryStatus.PENDING
            ):
                pending_msg.body = reply
                pending_msg.bot_run_id = run.id
                pending_msg.delivery_status = delivery_status
                pending_msg.external_error = external_error
                pending_msg.zalo_message_id = zalo_message_id
                msg = pending_msg
        if msg is None:
            msg = Message(
                conversation_id=conv.id,
                sender=MessageSender.BOT,
                body=reply,
                bot_run_id=run.id,
                delivery_status=delivery_status,
                external_error=external_error,
                zalo_message_id=zalo_message_id,
            )
            self.db.add(msg)
        conv.bot_locked_until = None
        if delivery_status == DeliveryStatus.SENT:
            conv.last_outbound_at = utcnow()
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def record_bot_pending(
        self,
        conv: Conversation,
        *,
        body: str = "Đang soạn trả lời...",
    ) -> Message:
        """Persist a visible pending BOT row without touching the version guard."""
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.BOT,
            body=body,
            delivery_status=DeliveryStatus.PENDING,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

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

    # --- proactive follow-up ---

    async def record_proactive_outcome(
        self,
        conv: Conversation,
        *,
        message: str,
        result: SendResult,
    ) -> Message:
        """Persist a proactive BOT message (no BotRun). Handles success/failure + cadence.

        On success: increments ``followup_count``, sets ``last_followup_at`` and
        ``last_outbound_at``, bumps version.  On failure: sets
        ``last_followup_attempt_at`` only (cadence budget is NOT consumed).
        Always clears the lock and fires realtime events.
        """
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.BOT,
            body=message,
            delivery_status=DeliveryStatus.SENT if result.ok else DeliveryStatus.FAILED,
            zalo_message_id=result.msg_id,
            external_error=None if result.ok else result.error,
        )
        self.db.add(msg)
        conv.bot_locked_until = None
        if result.ok:
            conv.last_outbound_at = utcnow()
            conv.last_followup_at = utcnow()
            conv.followup_count = (conv.followup_count or 0) + 1
            conv.version += 1
        else:
            conv.last_followup_attempt_at = utcnow()
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    # --- recruiter-side state transitions ---
    async def take_over(self, conv: Conversation, recruiter: User) -> Conversation:
        """Atomically claim a conversation. Uses conditional UPDATE so two recruiters
        racing on the same unassigned conversation produce exactly one winner and one
        ConversationConflict (mirrors acquire_lock pattern)."""
        now = utcnow()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv.id,
                or_(
                    Conversation.assigned_recruiter_id.is_(None),
                    Conversation.assigned_recruiter_id == recruiter.id,
                ),
            )
            .values(
                mode=ConversationMode.HUMAN,
                status=ConversationStatus.OPEN,
                assigned_recruiter_id=recruiter.id,
                taken_over_at=now,
                needs_human=False,
                unread_count=0,
                bot_locked_until=None,
                version=Conversation.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if res.rowcount == 0:
            await self.db.refresh(conv)
            raise ConversationConflict(
                "conversation is owned by another recruiter",
                owner_name=await _fetch_owner_name(self.db, conv),
            )
        await self.db.refresh(conv)
        self.db.add(
            Message(
                conversation_id=conv.id,
                sender=MessageSender.SYSTEM,
                body=f"{recruiter.full_name or 'Nhân viên'} đã tiếp nhận hội thoại.",
            )
        )
        await record_audit(
            self.db,
            action="take_over_conversation",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"version": conv.version},
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def release(self, conv: Conversation, actor: User) -> Conversation:
        conv.mode = ConversationMode.BOT
        conv.assigned_recruiter_id = None
        conv.taken_over_at = None
        conv.version += 1
        self.db.add(
            Message(
                conversation_id=conv.id,
                sender=MessageSender.SYSTEM,
                body="Hội thoại đã được trả lại cho chatbot.",
            )
        )
        await record_audit(
            self.db,
            action="release_to_bot",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def semi_auto(self, conv: Conversation, recruiter: User) -> Conversation:
        """Atomically enable semi-auto mode. Same conditional-UPDATE pattern as take_over."""
        now = utcnow()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv.id,
                or_(
                    Conversation.assigned_recruiter_id.is_(None),
                    Conversation.assigned_recruiter_id == recruiter.id,
                ),
            )
            .values(
                mode=ConversationMode.SEMI_AUTO,
                status=ConversationStatus.OPEN,
                assigned_recruiter_id=recruiter.id,
                taken_over_at=now,
                needs_human=False,
                unread_count=0,
                bot_locked_until=None,
                version=Conversation.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if res.rowcount == 0:
            await self.db.refresh(conv)
            raise ConversationConflict(
                "conversation is owned by another recruiter",
                owner_name=await _fetch_owner_name(self.db, conv),
            )
        await self.db.refresh(conv)
        self.db.add(
            Message(
                conversation_id=conv.id,
                sender=MessageSender.SYSTEM,
                body=(
                    f"{recruiter.full_name or 'Nhân viên'} đã bật chế độ bán tự động. "
                    "Chatbot sẽ trả lời nếu nhân viên không hoạt động trong 5 phút."
                ),
            )
        )
        await record_audit(
            self.db,
            action="semi_auto_conversation",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"version": conv.version, "inactive_after_seconds": 300},
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def close(self, conv: Conversation, actor: User) -> Conversation:
        conv.status = ConversationStatus.CLOSED
        conv.mode = ConversationMode.CLOSED
        conv.version += 1
        await record_audit(
            self.db,
            action="close_conversation",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def reopen(self, conv: Conversation, actor: User) -> Conversation:
        conv.status = ConversationStatus.OPEN
        conv.mode = ConversationMode.BOT
        conv.version += 1
        await record_audit(
            self.db,
            action="reopen_conversation",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def clear_history(self, conv: Conversation, actor: User) -> Conversation:
        """Hard-delete all messages + bot_runs and reset the conversation shell.

        The conversation row and its linked Lead are KEPT (zalo_chat_id identity
        preserved for inbound routing). Irreversible; admin-only at the router.
        """
        await self.db.execute(
            text("DELETE FROM messages WHERE conversation_id = :cid"), {"cid": conv.id}
        )
        await self.db.execute(
            text("DELETE FROM bot_runs WHERE conversation_id = :cid"), {"cid": conv.id}
        )
        conv.mode = ConversationMode.BOT
        conv.status = ConversationStatus.OPEN
        conv.needs_human = False
        conv.bot_locked_until = None
        conv.taken_over_at = None
        conv.assigned_recruiter_id = None
        conv.unread_count = 0
        conv.last_inbound_at = None
        conv.last_outbound_at = None
        conv.followup_count = 0
        conv.last_followup_at = None
        conv.last_followup_attempt_at = None
        conv.followup_opted_out = False
        conv.version += 1
        await record_audit(
            self.db,
            action="clear_conversation_history",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"hard_delete": "messages,bot_runs"},
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def mark_read(self, conv: Conversation) -> Conversation:
        conv.unread_count = 0
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def record_recruiter_message(
        self, conv: Conversation, recruiter: User, body: str, result: SendResult
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

    # --- OA webhook side events (receipts / lifecycle / interaction signals) ---

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
        if not zalo_message_id:
            return False
        if seen:
            target = DeliveryStatus.READ
        elif delivered:
            target = DeliveryStatus.DELIVERED
        else:
            return False
        msg = await self.db.scalar(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.zalo_message_id == zalo_message_id,
                Message.sender.in_([MessageSender.BOT, MessageSender.RECRUITER]),
            )
        )
        if msg is None:
            return False
        if _DELIVERY_RANK.get(msg.delivery_status, 0) >= _DELIVERY_RANK[target]:
            return False
        msg.delivery_status = target
        await self.db.commit()
        await self.events.conversation_updated(conv)
        return True

    async def record_system_note(self, conv: Conversation, *, body: str) -> Message:
        """Persist an informational SYSTEM message (button click, follow/unfollow).

        Does not bump ``unread_count`` or stamp ``last_inbound_at`` — it is CRM
        chrome, not an inbound worker message, and must not start a bot turn.
        """
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.SYSTEM,
            body=body,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def apply_follow(self, conv: Conversation) -> Conversation:
        """A user followed/returned to the OA: reopen if closed, clear needs_human.

        No ``version`` bump — follow is a CRM-visible refresh, not a takeover, and
        must not suppress an in-flight bot turn.
        """
        if conv.status == ConversationStatus.CLOSED:
            conv.status = ConversationStatus.OPEN
        conv.needs_human = False
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def apply_unfollow(self, conv: Conversation) -> Conversation:
        """A user unfollowed the OA: stop proactive follow-up and flag a recruiter.

        Sets ``followup_opted_out`` (the reconcile/proactive worker stops pestering
        a departed user) and ``needs_human``. No mode/status change — closing is a
        recruiter decision, not an automatic one.
        """
        conv.followup_opted_out = True
        conv.needs_human = True
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv
