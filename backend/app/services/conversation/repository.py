"""Data-access (read) layer for conversations.

All query methods — no mutation, no realtime publishing, no audit. Scope-filtering by
viewer role (admin = all, recruiter = own + unassigned) is applied here so callers stay
thin. Raw SQL stays where the ORM can't express it cleanly (``last_messages_batch`` uses
``DISTINCT ON`` + ``ANY(:ids)``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, asc, case, desc, func, or_, select, text

from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.contact import ContactChannelIdentity
from app.models.user import Role, User
from app.models.outbox import OutboundOutbox
from app.services.viewer_scope import viewer_scope_filter, viewer_scope_sql

# Whitelist of sortable conversation columns. Unknown / absent sort keys fall
# back to updated_at (the default inbox ordering).
_CONVERSATION_SORT = {
    "updated_at": Conversation.updated_at,
    "created_at": Conversation.created_at,
    "last_inbound_at": Conversation.last_inbound_at,
}


def _unanswered_inbound_condition():
    return and_(
        Conversation.status == ConversationStatus.OPEN,
        Conversation.mode == ConversationMode.HUMAN,
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

    async def get_visible(self, conv_id: uuid.UUID, *, viewer: User) -> Conversation | None:
        stmt = viewer_scope_filter(
            select(Conversation).where(Conversation.id == conv_id),
            Conversation.assigned_recruiter_id,
            viewer,
        )
        return (await self.db.scalars(stmt)).first()

    async def get_by_zalo(self, zalo_chat_id: str) -> Conversation | None:
        return (
            await self.db.scalars(
                select(Conversation).where(Conversation.zalo_chat_id == zalo_chat_id)
            )
        ).first()

    async def get_by_identity(
        self, *, provider: str, account_key: str, external_id: str
    ) -> Conversation | None:
        """Canonical lookup by neutral (provider, account_key, external_id).

        Replaces the soft ``zalo_chat_id`` match for new code. The conversation
        is joined to its ContactChannelIdentity, which carries the neutral triple.
        """
        return (
            await self.db.scalars(
                select(Conversation)
                .join(
                    ContactChannelIdentity,
                    Conversation.channel_identity_id == ContactChannelIdentity.id,
                )
                .where(
                    ContactChannelIdentity.provider == provider,
                    ContactChannelIdentity.account_key == account_key,
                    ContactChannelIdentity.external_id == external_id,
                )
            )
        ).first()

    async def get_visible_by_ids(self, *, viewer: User, ids: list[uuid.UUID]) -> list[Conversation]:
        """Viewer-scoped fetch of conversations by id list.

        Used by the attention-reason continuation (GET /conversations?reason=...)
        to resolve full Conversation rows for the conversation IDs the attention
        dashboard surfaced. Returns at most one row per id, viewer-scoped
        (admin = all, recruiter = own + unassigned). Empty id list short-circuits.
        """
        if not ids:
            return []
        stmt = viewer_scope_filter(
            select(Conversation).where(Conversation.id.in_(ids)),
            Conversation.assigned_recruiter_id,
            viewer,
        )
        return list((await self.db.scalars(stmt)).all())

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
            scope = "AND " + viewer_scope_sql("c.")
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
        channel_provider: str | None = None,
        q: str | None = None,
        sort_by: str | None = None,
        order: str | None = "desc",
    ) -> tuple[list[Conversation], int]:
        base = viewer_scope_filter(select(Conversation), Conversation.assigned_recruiter_id, viewer)
        if mode is not None:
            base = base.where(Conversation.mode == mode)
        if status is not None:
            base = base.where(Conversation.status == status)
        if zalo_chat_id:
            base = base.where(Conversation.zalo_chat_id == zalo_chat_id)
        if needs_attention:
            base = base.where(_unanswered_inbound_condition())
        if channel_provider is not None or q:
            # One identity join composes provider scope and neutral-id search.
            # Every current conversation has one canonical identity.
            base = base.join(
                ContactChannelIdentity,
                Conversation.channel_identity_id == ContactChannelIdentity.id,
            )
        if channel_provider is not None:
            base = base.where(ContactChannelIdentity.provider == channel_provider)
        if q:
            # Text search spans the Zalo compat alias and the neutral identity's
            # external_id so channel-neutral conversations remain searchable.
            pat = f"%{q}%"
            base = base.where(
                or_(
                    Conversation.zalo_chat_id.ilike(pat),
                    ContactChannelIdentity.external_id.ilike(pat),
                )
            )
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

    async def list_by_zalo_ids(
        self,
        *,
        viewer: User,
        zalo_chat_ids: list[str],
    ) -> list[Conversation]:
        if not zalo_chat_ids:
            return []
        query = viewer_scope_filter(
            select(Conversation),
            Conversation.assigned_recruiter_id,
            viewer,
        ).where(Conversation.zalo_chat_id.in_(zalo_chat_ids))
        rows = (
            await self.db.scalars(
                query.order_by(Conversation.updated_at.desc(), Conversation.id.asc())
            )
        ).all()
        return list(rows)

    async def needs_attention_count(
        self, *, viewer: User, channel_provider: str | None = None
    ) -> int:
        """Conversations the topbar bell should ring for: a Zalo user has sent
        a message after the latest successful bot/recruiter reply. Scoped like
        ``list`` (admin = all, recruiter = own + unassigned). Backs the
        notification badge so it never downloads conversation rows."""
        stmt = select(func.count()).select_from(Conversation).where(_unanswered_inbound_condition())
        if channel_provider is not None:
            stmt = stmt.join(
                ContactChannelIdentity,
                Conversation.channel_identity_id == ContactChannelIdentity.id,
            ).where(ContactChannelIdentity.provider == channel_provider)
        stmt = viewer_scope_filter(stmt, Conversation.assigned_recruiter_id, viewer)
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
        messages = list(reversed(rows))
        await self._attach_delivery_attempts(messages)
        return messages

    async def _attach_delivery_attempts(self, messages: list[Message]) -> None:
        """Attach outbox attempts for API/realtime serialization without N+1 queries."""
        ids = [message.id for message in messages if message.id is not None]
        if not ids:
            return
        rows = (
            await self.db.execute(
                select(OutboundOutbox.message_id, OutboundOutbox.attempts).where(
                    OutboundOutbox.message_id.in_(ids)
                )
            )
        ).all()
        attempts_by_id = {int(row.message_id): int(row.attempts or 0) for row in rows}
        for message in messages:
            message._delivery_attempts = attempts_by_id.get(int(message.id), 0)

    async def latest_message(self, conv: Conversation) -> Message | None:
        return (
            await self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(desc(Message.created_at), desc(Message.id))
                .limit(1)
            )
        ).first()

    async def latest_worker_message(self, conv: Conversation) -> Message | None:
        """Return the latest inbound Zalo message for a conversation.

        Zalo OA consultation replies must quote an inbound message id, even if
        a prior bot or recruiter reply has already answered that message.
        """
        return (
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
        messages = list(reversed(rows))
        await self._attach_delivery_attempts(messages)
        return messages

    async def messages_since(
        self, conv: Conversation, since_id: int | None = None, limit: int = 200
    ) -> list[Message]:
        """Chronological list of messages NEWER than the `since_id` cursor (the
        integer id of the newest currently-loaded message). Used for reconnect
        gap-fill: when the Socket.IO transport reconnects after a disconnect, the
        client calls this to fetch any messages the server emitted while it was
        offline. Returns oldest-first (chronological) for direct merge into the
        loaded window. If since_id is None/unknown, returns the newest page."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(asc(Message.created_at), asc(Message.id))
            .limit(limit)
        )
        if since_id is not None:
            cursor = await self.db.get(Message, since_id)
            if cursor is None or cursor.conversation_id != conv.id:
                # Unknown cursor — fall back to newest page.
                stmt = (
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(desc(Message.created_at), desc(Message.id))
                    .limit(limit)
                )
                rows = (await self.db.scalars(stmt)).all()
                messages = list(reversed(rows))
                await self._attach_delivery_attempts(messages)
                return messages
            stmt = stmt.where(
                or_(
                    Message.created_at > cursor.created_at,
                    and_(
                        Message.created_at == cursor.created_at,
                        Message.id > cursor.id,
                    ),
                )
            )
        rows = (await self.db.scalars(stmt)).all()
        messages = list(rows)
        await self._attach_delivery_attempts(messages)
        return messages

    async def latest_unanswered_worker_message(self, conv: Conversation) -> Message | None:
        """Return the latest Zalo user message if no confirmed outbound follows it.

        Zalo receipts advance a successfully sent message from ``SENT`` to
        ``DELIVERED`` or ``READ``. All three states answer the candidate message;
        treating only ``SENT`` as an answer makes releasing a human-managed
        conversation requeue an already answered inbound message.
        """
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
                    Message.delivery_status.in_(
                        [
                            DeliveryStatus.SENT,
                            DeliveryStatus.DELIVERED,
                            DeliveryStatus.READ,
                        ]
                    ),
                )
                .limit(1)
            )
        ).first()
        return None if answered is not None else worker_msg

    async def find_reconcile_candidates(
        self,
        *,
        now: datetime,
        grace_seconds: int,
        max_age_seconds: int,
        limit: int,
        stale_lock_seconds: int = 60,
    ) -> list[Conversation]:
        """Conversations whose newest message is unanswered or recoverable BOT failure.

        Loop-free predicate: a completed turn (sent or suppressed) leaves a
        ``BOT/SENT`` or ``BOT/SUPPRESSED`` row as the newest message, so it is
        excluded.  Only ``WORKER`` (never processed), ``BOT/PENDING`` (turn
        started but never completed), ``BOT/SENDING`` (claimed but never confirmed
        — a worker crash after the POST; reconciled as sent-but-unconfirmed), or
        ``BOT/FAILED`` (Zalo rejected delivery) qualify, except for the known
        permanent OA recipient rejection.

        A conversation whose per-chat lock is still live but whose owner heartbeat
        is older than ``stale_lock_seconds`` (the RQ job-timeout horizon) is also
        included, so a crashed worker's lock can be force-broken and the turn
        recovered instead of waiting the full ``bot_lock_ttl``.

        SEMI_AUTO 5-min-inactivity is NOT in SQL — it is re-checked in Python
        inside the tick (depends on ``taken_over_at``/``updated_at``).
        """
        now_minus_grace = now - timedelta(seconds=grace_seconds)
        now_minus_max_age = now - timedelta(seconds=max_age_seconds)
        now_minus_stale_lock = now - timedelta(seconds=stale_lock_seconds)
        # NOTE: use select(Conversation).from_statement(text(...)) instead of
        # db.scalars(text(...)) — the latter returns only the first column (c.id
        # as a raw asyncpg UUID) rather than a Conversation ORM instance, causing
        # AttributeError downstream in reconcile_worker when it accesses conv.id.
        stmt = select(Conversation).from_statement(
            text(
                """
                    SELECT c.*
                      FROM conversations c
                     WHERE c.mode IN ('BOT', 'SEMI_AUTO')
                       AND (
                           c.bot_locked_until IS NULL
                           OR c.bot_locked_until < :now
                           OR (
                               c.bot_locked_until IS NOT NULL
                               AND c.bot_lock_heartbeat_at IS NOT NULL
                               AND c.bot_lock_heartbeat_at < :stale_cutoff
                           )
                       )
                       AND c.status = 'OPEN'
                       AND (c.followup_opted_out = FALSE OR c.followup_opted_out IS NULL)
                       AND EXISTS (
                           SELECT 1 FROM messages m
                            WHERE m.conversation_id = c.id
                              AND m.id = (
                                  SELECT m2.id FROM messages m2
                                   WHERE m2.conversation_id = c.id
                                   ORDER BY m2.created_at DESC, m2.id DESC
                                   LIMIT 1
                              )
                              AND (
                                  m.sender = 'WORKER'
                                  OR (
                                      m.sender = 'BOT'
                                      AND m.delivery_status IN ('PENDING', 'SENDING', 'FAILED')
                                      AND NOT (
                                          m.delivery_status = 'FAILED'
                                          AND c.zalo_channel = 'oa'
                                          AND lower(COALESCE(m.external_error, ''))
                                              LIKE '%user_id is invalid%'
                                      )
                                  )
                              )
                              AND m.created_at < :now_minus_grace
                              AND m.created_at > :now_minus_max_age
                       )
                     ORDER BY c.last_inbound_at DESC NULLS LAST
                     LIMIT :limit
                    """
            )
        )
        rows = (
            await self.db.scalars(
                stmt,
                {
                    "now": now,
                    "now_minus_grace": now_minus_grace,
                    "now_minus_max_age": now_minus_max_age,
                    "stale_cutoff": now_minus_stale_lock,
                    "limit": limit,
                },
            )
        ).all()
        return list(rows)
