"""Conversation state mutations + orchestration (the takeover race-guard core).

Replaces the n8n Ensure / Run-Start-Guard / Acquire-Lock / Recheck-Ownership nodes and
the vfic_take_over / release / mark_read edge functions. All state changes bump
``version`` (the optimistic-lock token) and fan out a realtime event via the event bus.

Reads live in ``repository.py``; realtime publishing in ``events.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, update

from app.core.config import get_settings
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


class ConversationConflict(Exception):
    """Raised when a recruiter tries to take over a conversation owned by another."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationState:
    """Mutates conversation/message rows + records audit + publishes realtime events.

    Composes a ``ConversationRepository`` (for reads within mutations) and a
    ``ConversationEventBus`` (for publishing). Pure orchestration — no new business
    rules vs. the legacy single class.
    """

    def __init__(self, db, repo, events) -> None:
        self.db = db
        self.repo = repo
        self.events = events

    # --- webhook-side primitives (used by US-006 chatbot) ---
    async def ensure(self, zalo_chat_id: str) -> Conversation:
        conv = await self.repo.get_by_zalo(zalo_chat_id)
        if conv is None:
            conv = Conversation(zalo_chat_id=zalo_chat_id)
            self.db.add(conv)
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
        if conv.mode != ConversationMode.BOT:
            conv.unread_count = (conv.unread_count or 0) + 1
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
        """Pre-send guard: bot may send only if eligible and version unchanged."""
        return self.run_start_guard(conv) and conv.version == version_at_start

    async def record_bot_outcome(
        self,
        conv: Conversation,
        *,
        version_at_start: int,
        reply: str,
        started_at: datetime,
        sent: bool,
    ) -> Message:
        """Log a bot_run + the (possibly suppressed) BOT message; clears the lock."""
        outcome = BotRunOutcome.SENT if sent else BotRunOutcome.SUPPRESSED
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
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.BOT,
            body=reply,
            bot_run_id=run.id,
            delivery_status=DeliveryStatus.SENT if sent else DeliveryStatus.SUPPRESSED,
        )
        self.db.add(msg)
        conv.bot_locked_until = None
        if sent:
            conv.last_outbound_at = utcnow()
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    # --- recruiter-side state transitions ---
    async def take_over(self, conv: Conversation, recruiter: User) -> Conversation:
        if conv.assigned_recruiter_id not in (None, recruiter.id):
            raise ConversationConflict("conversation is owned by another recruiter")
        conv.mode = ConversationMode.HUMAN
        conv.status = ConversationStatus.OPEN
        conv.assigned_recruiter_id = recruiter.id
        conv.taken_over_at = utcnow()
        conv.needs_human = False
        conv.unread_count = 0
        # A human takeover releases any in-flight bot mutex: mode is now HUMAN so the
        # bot cannot run anyway, and leaving bot_locked_until set would cause every
        # subsequent inbound from this candidate to be silently dropped until the TTL.
        conv.bot_locked_until = None
        conv.version += 1
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
        if conv.assigned_recruiter_id not in (None, recruiter.id):
            raise ConversationConflict("conversation is owned by another recruiter")
        conv.mode = ConversationMode.SEMI_AUTO
        conv.status = ConversationStatus.OPEN
        conv.assigned_recruiter_id = recruiter.id
        conv.taken_over_at = utcnow()
        conv.needs_human = False
        conv.unread_count = 0
        conv.bot_locked_until = None
        conv.version += 1
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
