"""Recruiter lifecycle path of the conversation state layer.

Owns the recruiter-side lifecycle transitions: take over, release, semi-auto,
close/reopen, clear history, delete, mark read, plus the SYSTEM notes and
follow/unfollow the OA webhook writes against a conversation.

Recruiter replies, their delivery finalization and Zalo delivery receipts live
in ``recruiter_receipts.py`` and are mixed in below. Bot-send logic lives in
``bot_path.py``; shared helpers in ``_shared.py``.
"""

from __future__ import annotations

from sqlalchemy import and_, or_, text, update

from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationProjectState,
    ConversationStatus,
    Message,
    MessageSender,
)
from app.models.user import Role, User
from app.services.audit_service import record_audit
from app.services.conversation._shared import affected_rows, utcnow
from app.services.conversation.recruiter_receipts import RecruiterReceiptsMixin


class ConversationConflict(Exception):
    """Raised when a recruiter tries to take over a conversation owned by another."""

    def __init__(self, message: str = "", owner_name: str | None = None) -> None:
        super().__init__(message)
        self.owner_name = owner_name


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


class RecruiterMessagingState(RecruiterReceiptsMixin):
    """Recruiter half of the former ``ConversationState``.

    Lifecycle transitions, system notes and follow/unfollow, plus the replies and
    delivery receipts mixed in from ``recruiter_receipts.py``. Composes a
    ``ConversationEventBus`` (for publishing). Pure orchestration — no new
    business rules.
    """

    def __init__(self, db, events) -> None:
        self.db = db
        self.events = events


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
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
                conversation_seq=Conversation.conversation_seq + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if affected_rows(res) == 0:
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
        conditions = [Conversation.id == conv.id]
        if actor.role != Role.admin:
            conditions.append(
                or_(
                    Conversation.assigned_recruiter_id == actor.id,
                    and_(
                        Conversation.assigned_recruiter_id.is_(None),
                        Conversation.needs_human.is_(False),
                    ),
                )
            )
        released = await self.db.execute(
            update(Conversation)
            .where(*conditions)
            .values(
                mode=ConversationMode.BOT,
                assigned_recruiter_id=None,
                taken_over_at=None,
                needs_human=False,
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
                conversation_seq=Conversation.conversation_seq + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if affected_rows(released) == 0:
            await self.db.rollback()
            await self.db.refresh(conv)
            owner_name = (
                await _fetch_owner_name(self.db, conv)
                if conv.assigned_recruiter_id is not None
                else None
            )
            raise ConversationConflict(
                "conversation must be claimed before release",
                owner_name=owner_name,
            )
        await self.db.refresh(conv)
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
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
                conversation_seq=Conversation.conversation_seq + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if affected_rows(res) == 0:
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
        conv.conversation_seq += 1
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
        conv.conversation_seq += 1
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
        conv.bot_lock_owner = None
        conv.bot_lock_heartbeat_at = None
        conv.taken_over_at = None
        conv.assigned_recruiter_id = None
        conv.unread_count = 0
        conv.last_inbound_at = None
        conv.last_outbound_at = None
        conv.followup_count = 0
        conv.last_followup_at = None
        conv.last_followup_attempt_at = None
        conv.followup_opted_out = False
        conv.project_context_state = ConversationProjectState.EXPLORE
        conv.focused_project_id = None
        conv.version += 1
        conv.conversation_seq += 1
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

    async def delete(self, conv: Conversation, actor: User) -> None:
        """Hard-delete a spam or test conversation while retaining its Lead.

        The database cascades the conversation deletion to messages and bot runs.
        Audit rows store the conversation id as text, so the deletion remains
        traceable after the source row is gone. Admin-only enforcement lives at
        the API boundary.
        """
        await record_audit(
            self.db,
            action="delete_conversation",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"hard_delete": "conversation,messages,bot_runs"},
        )
        await self.db.delete(conv)
        await self.db.commit()

    async def mark_read(self, conv: Conversation) -> Conversation:
        conv.unread_count = 0
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

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
