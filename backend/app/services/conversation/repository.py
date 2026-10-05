"""Data-access (read) layer for conversations.

Viewer-scoped CRM inbox reads: get/list/paginate/message history and the
attention count. Scope-filtering by viewer role (admin = all, recruiter = own +
unassigned) is applied here so callers stay thin. Raw SQL stays where the ORM
can't express it cleanly (``last_messages_batch`` uses ``DISTINCT ON`` +
``ANY(:ids)``).

The reconcile sweep's SQL lives in ``reconcile_queries.py`` and is mixed in
below, so its masked-inbound fragment has exactly one definition.
"""

from __future__ import annotations

import uuid

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
from app.services.conversation.reconcile_queries import (
    SUPERSEDED_OUTCOME_STATUSES,
    ReconcileQueriesMixin,
)
from app.services.viewer_scope import (
    support_account_sql,
    viewer_conversation_filter,
    viewer_scope_sql,
)

__all__ = [
    "SUPERSEDED_OUTCOME_STATUSES",
    "ConversationRepository",
    "ReconcileQueriesMixin",
]

# Whitelist of sortable conversation columns. Unknown / absent sort keys fall
# back to the inbox default.
_CONVERSATION_SORT = {
    "updated_at": Conversation.updated_at,
    "created_at": Conversation.created_at,
    "last_inbound_at": Conversation.last_inbound_at,
    # Inbox default: the latest candidate message, falling back to the row's
    # update time. ``updated_at`` alone is unreliable — batch maintenance
    # (backfills/migrations) touches it without a new message, which scrambles
    # the inbox against the timestamp each row actually displays.
    "last_message_at": func.coalesce(Conversation.last_inbound_at, Conversation.updated_at),
}
_CONVERSATION_DEFAULT_SORT = "last_message_at"



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


class ConversationRepository(ReconcileQueriesMixin):
    def __init__(self, db) -> None:
        self.db = db

    async def get(self, conv_id: uuid.UUID) -> Conversation | None:
        return await self.db.get(Conversation, conv_id)

    async def get_visible(self, conv_id: uuid.UUID, *, viewer: User) -> Conversation | None:
        stmt = viewer_conversation_filter(
            select(Conversation).where(Conversation.id == conv_id), viewer
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
        stmt = viewer_conversation_filter(
            select(Conversation).where(Conversation.id.in_(ids)), viewer
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
            # Same invariant as viewer_conversation_filter, in raw SQL: the
            # recruiter's own-or-unassigned rule plus the admin-only support OA.
            scope = "AND " + viewer_scope_sql("c.") + " AND " + support_account_sql("c.")
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

    @staticmethod
    def _channel_filter_condition(channel_provider: str):
        """Identity predicate for one channel filter value.

        ``tingting_oa`` is not a provider: it is the employee-support OA account
        (provider ``zalo_oa``), so the badge narrows on the account key. The two
        Zalo OA badges are disjoint — the plain ``zalo_oa`` badge is the
        recruitment OA and must not return support threads, or clicking it would
        mix TingTing chats into the recruitment inbox.
        """
        from app.channels import types as ct
        from app.channels.types import TINGTING_OA_ACCOUNT_KEY

        if channel_provider == "tingting_oa":
            return and_(
                ContactChannelIdentity.provider == ct.PROVIDER_ZALO_OA,
                ContactChannelIdentity.account_key == TINGTING_OA_ACCOUNT_KEY,
            )
        if channel_provider == "zalo_oa":
            # A NULL account key predates the multi-OA split and is the
            # recruitment OA, so it stays in scope; only the support key is out.
            return and_(
                ContactChannelIdentity.provider == ct.PROVIDER_ZALO_OA,
                or_(
                    ContactChannelIdentity.account_key.is_(None),
                    ContactChannelIdentity.account_key != TINGTING_OA_ACCOUNT_KEY,
                ),
            )
        return ContactChannelIdentity.provider == channel_provider

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
        base = viewer_conversation_filter(select(Conversation), viewer)
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
            base = base.where(self._channel_filter_condition(channel_provider))
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
        sort_col = _CONVERSATION_SORT.get((sort_by or _CONVERSATION_DEFAULT_SORT).lower())
        if sort_col is None:
            sort_col = _CONVERSATION_SORT[_CONVERSATION_DEFAULT_SORT]
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
        query = viewer_conversation_filter(select(Conversation), viewer).where(
            Conversation.zalo_chat_id.in_(zalo_chat_ids)
        )
        rows = (
            await self.db.scalars(
                query.order_by(Conversation.updated_at.desc(), Conversation.id.asc())
            )
        ).all()
        return list(rows)

    async def list_by_contact_ids(
        self,
        *,
        viewer: User,
        contact_ids: list[uuid.UUID],
    ) -> list[Conversation]:
        """Conversations of the given contacts, newest activity first.

        Contact-keyed counterparts of :meth:`list_by_zalo_ids`: Messenger and
        other contact-keyed rows carry a NULL ``zalo_chat_id`` (Alembic 0047),
        so a chat-id lookup can never reach them.
        """
        if not contact_ids:
            return []
        query = viewer_conversation_filter(select(Conversation), viewer).where(
            Conversation.contact_id.in_(contact_ids)
        )
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
            ).where(self._channel_filter_condition(channel_provider))
        stmt = viewer_conversation_filter(stmt, viewer)
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

    async def inbound_is_answered(
        self, conv: Conversation, *, provider_message_id: str
    ) -> bool:
        """Whether an inbound message already has a delivered answer.

        A channel may redeliver the same inbound (Zalo retries its webhook; the
        ingress is idempotent on the provider id, so the redelivery persists
        nothing) — but the redelivery still enqueues a turn, and a turn that runs
        after the first one finished sends the candidate a SECOND copy of the same
        reply. Production 2026-10-05: one "Có lương chưa" produced two identical
        OA replies 35 s apart, from two turns both quoting the same inbound.

        Only a TERMINAL status counts as an answer: a PENDING placeholder belongs
        to an in-flight turn (its own lock still holds), and a FAILED reply never
        reached the candidate, so neither may suppress the turn that recovers it.
        """
        inbound_at = await self.db.scalar(
            select(Message.created_at).where(
                Message.conversation_id == conv.id,
                Message.provider_message_id == provider_message_id,
            )
        )
        if inbound_at is None:
            return False
        answered = await self.db.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == conv.id,
                Message.sender == MessageSender.BOT,
                Message.delivery_status.in_(SUPERSEDED_OUTCOME_STATUSES),
                Message.created_at >= inbound_at,
            )
            .limit(1)
        )
        return answered is not None

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

