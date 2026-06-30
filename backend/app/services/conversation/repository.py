"""Data-access (read) layer for conversations.

All query methods — no mutation, no realtime publishing, no audit. Scope-filtering by
viewer role (admin = all, recruiter = own + unassigned) is applied here so callers stay
thin. Raw SQL stays where the ORM can't express it cleanly (``last_messages_batch`` uses
``DISTINCT ON`` + ``ANY(:ids)``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, case, desc, func, or_, select, text

from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.user import Role, User

# Whitelist of sortable conversation columns. Unknown / absent sort keys fall
# back to updated_at (the default inbox ordering).
_CONVERSATION_SORT = {
    "updated_at": Conversation.updated_at,
    "created_at": Conversation.created_at,
    "last_inbound_at": Conversation.last_inbound_at,
}


def _unanswered_inbound_condition():
    return and_(
        Conversation.mode.in_([ConversationMode.HUMAN, ConversationMode.SEMI_AUTO]),
        Conversation.last_inbound_at.is_not(None),
        or_(
            Conversation.last_outbound_at.is_(None),
            Conversation.last_inbound_at > Conversation.last_outbound_at,
        ),
    )


class ConversationRepository:
    def __init__(self, db) -> None:
        self.db = db

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
        needs_attention: bool = False,
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
        if needs_attention:
            base = base.where(_unanswered_inbound_condition())
        if q:
            base = base.where(Conversation.zalo_chat_id.ilike(f"%{q}%"))
        total = await self.db.scalar(select(func.count()).select_from(base.subquery()))
        sort_col = _CONVERSATION_SORT.get((sort_by or "").lower()) or Conversation.updated_at
        order_expr = sort_col.asc() if (order or "desc").lower() == "asc" else sort_col.desc()
        mode_order_expr = case(
            (Conversation.mode == ConversationMode.HUMAN, 0),
            (Conversation.mode == ConversationMode.SEMI_AUTO, 1),
            (Conversation.mode == ConversationMode.BOT, 2),
            else_=3,
        )
        unanswered_expr = case(
            (
                _unanswered_inbound_condition(),
                1,
            ),
            else_=0,
        )
        rows = (
            await self.db.scalars(
                base.order_by(mode_order_expr.asc(), unanswered_expr.desc(), order_expr)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    async def needs_attention_count(self, *, viewer: User) -> int:
        """Conversations the topbar bell should ring for: a Zalo user has sent
        a message after the latest successful bot/recruiter reply. Scoped like
        ``list`` (admin = all, recruiter = own + unassigned). Backs the
        notification badge so it never downloads conversation rows."""
        stmt = (
            select(func.count())
            .select_from(Conversation)
            .where(_unanswered_inbound_condition())
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
        integer message id of the oldest currently-loaded message) is set,
        resolve that row and return the page older than its (created_at, id)
        cursor. Results are reversed to chronological order for the chat
        scroller. Used for cursor-based load-more."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(limit)
        )
        if before_id is not None:
            cursor = await self.db.get(Message, before_id)
            if cursor is None or cursor.conversation_id != conv.id:
                return []
            stmt = stmt.where(
                or_(
                    Message.created_at < cursor.created_at,
                    and_(
                        Message.created_at == cursor.created_at,
                        Message.id < cursor.id,
                    ),
                )
            )
        rows = (await self.db.scalars(stmt)).all()
        return list(reversed(rows))

    async def latest_unanswered_worker_message(self, conv: Conversation) -> Message | None:
        """Return the latest Zalo user message if no successful outbound follows it."""
        worker_msg = (
            await self.db.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.sender == MessageSender.WORKER,
                )
                .order_by(desc(Message.created_at), desc(Message.id))
                .limit(1)
            )
        ).first()
        if worker_msg is None:
            return None

        answered = (
            await self.db.scalars(
                select(Message.id)
                .where(
                    Message.conversation_id == conv.id,
                    Message.id > worker_msg.id,
                    Message.sender.in_([MessageSender.BOT, MessageSender.RECRUITER]),
                    Message.delivery_status == DeliveryStatus.SENT,
                )
                .limit(1)
            )
        ).first()
        return None if answered is not None else worker_msg
