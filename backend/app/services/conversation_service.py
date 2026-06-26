"""Conversation lifecycle + ownership (the core of the takeover race-guard).

This replaces the n8n Ensure/Run-Start-Guard/Acquire-Lock/Recheck-Ownership nodes
and the vfic_take_over/release/mark_read edge functions. All state changes bump
`version` (the optimistic-lock token) and fan out a realtime event.

NOTE: `from __future__ import annotations` is required because this module defines a
method named `list`, which would otherwise shadow the builtin `list` during class-body
annotation evaluation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select, text, update

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
from app.core.config import get_settings
from app.models.user import Role, User
from app.schemas.conversation import ConversationOut
from app.services.audit_service import record_audit
from app.services.realtime import publish_event
from app.services.zalo_service import SendResult

_settings = get_settings()


class ConversationConflict(Exception):
    """Raised when a recruiter tries to take over a conversation owned by another."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Whitelist of sortable conversation columns. Unknown / absent sort keys fall
# back to updated_at (the default inbox ordering).
_CONVERSATION_SORT = {
    "updated_at": Conversation.updated_at,
    "created_at": Conversation.created_at,
    "last_inbound_at": Conversation.last_inbound_at,
}


def _conv_payload(conv: Conversation) -> dict:
    return ConversationOut.model_validate(conv).model_dump(mode="json")


class ConversationService:
    def __init__(self, db) -> None:
        self.db = db

    # --- read ---
    async def get(self, conv_id: uuid.UUID) -> Conversation | None:
        return await self.db.get(Conversation, conv_id)

    async def get_by_zalo(self, zalo_chat_id: str) -> Conversation | None:
        return (
            await self.db.scalars(
                select(Conversation).where(Conversation.zalo_chat_id == zalo_chat_id)
            )
        ).first()

    async def last_messages_batch(self, *, viewer: User, ids_str: str) -> dict[str, str]:
        """Latest message body per conversation, in ONE set-based query.

        Replaces the client-side N-fanout (one GET /conversations/{id}/last-messages
        per inbox row). Scope-filtered to the viewer (admin = all, recruiter = their
        own + unassigned), id list parsed + capped at 200.
        """
        # Parse comma-separated UUIDs; ignore garbage; cap to 200.
        ids: list[str] = []
        for token in (ids_str or "").split(","):
            s = token.strip()
            if not s:
                continue
            try:
                ids.append(str(uuid.UUID(s)))
            except ValueError:
                continue
            if len(ids) >= 200:
                break
        if not ids:
            return {}

        params: dict = {"ids": ids}
        scope = ""
        if viewer.role != Role.admin:
            scope = "AND (c.assigned_recruiter_id = :uid OR c.assigned_recruiter_id IS NULL)"
            params["uid"] = str(viewer.id)

        rows = (
            await self.db.execute(
                text(
                    f"""
                    SELECT DISTINCT ON (m.conversation_id)
                           m.conversation_id::text AS cid, m.body AS content
                      FROM messages m
                      JOIN conversations c ON c.id = m.conversation_id
                     WHERE m.conversation_id = ANY(:ids) {scope}
                     ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
                    """
                ),
                params,
            )
        ).all()
        return {r.cid: (r.content or "") for r in rows}

    async def list(
        self,
        *,
        viewer: User,
        page: int = 1,
        per_page: int = 25,
        mode: ConversationMode | None = None,
        status: ConversationStatus | None = None,
        zalo_chat_id: str | None = None,
        q: str | None = None,
        sort_by: str | None = None,
        order: str | None = "desc",
    ) -> tuple[list[Conversation], int]:
        base = select(Conversation)
        if viewer.role != Role.admin:
            # recruiters see their own + unassigned
            base = base.where(
                or_(
                    Conversation.assigned_recruiter_id == viewer.id,
                    Conversation.assigned_recruiter_id.is_(None),
                )
            )
        if mode is not None:
            base = base.where(Conversation.mode == mode)
        if status is not None:
            base = base.where(Conversation.status == status)
        if zalo_chat_id:
            base = base.where(Conversation.zalo_chat_id == zalo_chat_id)
        if q:
            base = base.where(Conversation.zalo_chat_id.ilike(f"%{q}%"))
        total = await self.db.scalar(select(func.count()).select_from(base.subquery()))
        sort_col = _CONVERSATION_SORT.get((sort_by or "").lower()) or Conversation.updated_at
        order_expr = sort_col.asc() if (order or "desc").lower() == "asc" else sort_col.desc()
        rows = (
            await self.db.scalars(
                base.order_by(order_expr).offset((page - 1) * per_page).limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    async def needs_attention_count(self, *, viewer: User) -> int:
        """Conversations the topbar bell should ring for: in recruiter takeover
        (mode=HUMAN) OR with unread inbound (unread_count > 0). Scoped like
        ``list`` (admin = all, recruiter = own + unassigned). Backs the
        notification badge so it never downloads conversation rows."""
        stmt = select(func.count()).select_from(Conversation).where(
            or_(
                Conversation.mode == ConversationMode.HUMAN,
                Conversation.unread_count > 0,
            )
        )
        if viewer.role != Role.admin:
            stmt = stmt.where(
                or_(
                    Conversation.assigned_recruiter_id == viewer.id,
                    Conversation.assigned_recruiter_id.is_(None),
                )
            )
        return int((await self.db.scalar(stmt)) or 0)

    async def last_messages(self, conv: Conversation, limit: int = 50) -> list[Message]:
        rows = (
            await self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(desc(Message.created_at), desc(Message.id))
                .limit(limit)
            )
        ).all()
        return list(reversed(rows))

    async def messages_page(
        self, conv: Conversation, limit: int = 50, before_id: int | None = None
    ) -> list[Message]:
        """Newest-first page of a conversation's messages; when `before_id` (the
        integer message id of the oldest currently-visible message) is set, return
        the page older than that cursor. Results are reversed to chronological
        order for the chat scroller. Used for cursor-based load-more."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(limit)
        )
        if before_id is not None:
            stmt = stmt.where(Message.id < before_id)
        rows = (await self.db.scalars(stmt)).all()
        return list(reversed(rows))

    # --- webhook-side primitives (used by US-006 chatbot) ---
    async def ensure(self, zalo_chat_id: str) -> Conversation:
        conv = await self.get_by_zalo(zalo_chat_id)
        if conv is None:
            conv = Conversation(zalo_chat_id=zalo_chat_id)
            self.db.add(conv)
            await self.db.flush()
        return conv

    def run_start_guard(self, conv: Conversation) -> bool:
        """True only when the bot may run (mode == BOT). HUMAN/CLOSED starves it."""
        return conv.mode == ConversationMode.BOT

    async def record_inbound(self, conv: Conversation) -> Conversation:
        """An inbound worker message arrived: stamp time, bump unread if not bot-owned."""
        conv.last_inbound_at = utcnow()
        if conv.mode != ConversationMode.BOT:
            conv.unread_count = (conv.unread_count or 0) + 1
        await self.db.commit()
        await publish_event("conversation.updated", _conv_payload(conv))
        return conv

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

    async def recheck_ownership(
        self, conv: Conversation, version_at_start: int
    ) -> bool:
        """Pre-send guard: bot may send only if still BOT and version unchanged."""
        return conv.mode == ConversationMode.BOT and conv.version == version_at_start

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
        await publish_event("message.created", {"message_id": msg.id, "conversation_id": str(conv.id)})
        await publish_event("conversation.updated", _conv_payload(conv))
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
        await publish_event("conversation.updated", _conv_payload(conv))
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
        await record_audit(self.db, action="release_to_bot", actor_id=actor.id, target_type="conversation", target_id=str(conv.id))
        await self.db.commit()
        await self.db.refresh(conv)
        await publish_event("conversation.updated", _conv_payload(conv))
        return conv

    async def close(self, conv: Conversation, actor: User) -> Conversation:
        conv.status = ConversationStatus.CLOSED
        conv.mode = ConversationMode.CLOSED
        conv.version += 1
        await record_audit(self.db, action="close_conversation", actor_id=actor.id, target_type="conversation", target_id=str(conv.id))
        await self.db.commit()
        await self.db.refresh(conv)
        await publish_event("conversation.updated", _conv_payload(conv))
        return conv

    async def reopen(self, conv: Conversation, actor: User) -> Conversation:
        conv.status = ConversationStatus.OPEN
        conv.mode = ConversationMode.BOT
        conv.version += 1
        await record_audit(self.db, action="reopen_conversation", actor_id=actor.id, target_type="conversation", target_id=str(conv.id))
        await self.db.commit()
        await self.db.refresh(conv)
        await publish_event("conversation.updated", _conv_payload(conv))
        return conv

    async def mark_read(self, conv: Conversation) -> Conversation:
        conv.unread_count = 0
        await self.db.commit()
        await self.db.refresh(conv)
        await publish_event("conversation.updated", _conv_payload(conv))
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
        await publish_event("message.created", {"message_id": msg.id, "conversation_id": str(conv.id)})
        await publish_event("conversation.updated", _conv_payload(conv))
        return msg
