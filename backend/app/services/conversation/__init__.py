"""Conversation lifecycle service package (repository + state + events).

Public API: ``ConversationService`` (a facade composing a repository, an event bus, and
a state machine) + ``ConversationConflict``; importers should depend on
``app.services.conversation`` rather than the internal submodules.

NOTE: ``from __future__ import annotations`` is required because this module defines a
method named ``list``, which would otherwise shadow the builtin ``list`` during class-body
annotation evaluation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.conversation.events import ConversationEventBus
from app.services.conversation.repository import ConversationRepository
from app.services.conversation.scheduler import enqueue_latest_unanswered_worker_message
from app.services.conversation.state import ConversationConflict, ConversationState

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from datetime import datetime

    from app.models.conversation import (
        Conversation,
        ConversationMode,
        ConversationStatus,
        DeliveryStatus,
        Message,
    )
    from app.models.user import User
    from app.services.zalo_bot_service import SendResult

__all__ = ["ConversationConflict", "ConversationService"]


class ConversationService:
    """Facade over the conversation read/state/event layers.

    Composes :class:`ConversationRepository` (reads), :class:`ConversationEventBus`
    (realtime publishing), and :class:`ConversationState` (mutations + orchestration),
    then re-exposes the union of their public methods with identical signatures so the
    three consumers (``graph/runner``, ``services/webhook``, ``api/conversations``) need
    no import changes. ``self.db`` is preserved for callers that refresh the session
    directly (e.g. ``graph/runner.run_turn``).
    """

    def __init__(self, db) -> None:
        self.db = db
        self.repo = ConversationRepository(db)
        self.events = ConversationEventBus(db)
        self.state = ConversationState(db, self.repo, self.events)

    # --- reads (delegate to repository) ---
    async def get(self, conv_id: uuid.UUID) -> Conversation | None:
        return await self.repo.get(conv_id)

    async def get_visible(self, conv_id: uuid.UUID, *, viewer: User) -> Conversation | None:
        return await self.repo.get_visible(conv_id, viewer=viewer)

    async def get_by_zalo(self, zalo_chat_id: str) -> Conversation | None:
        return await self.repo.get_by_zalo(zalo_chat_id)

    async def last_messages_batch(self, *, viewer: User, ids_str: str) -> dict[str, str]:
        return await self.repo.last_messages_batch(viewer=viewer, ids_str=ids_str)

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
        return await self.repo.list(
            viewer=viewer,
            page=page,
            per_page=per_page,
            mode=mode,
            status=status,
            zalo_chat_id=zalo_chat_id,
            needs_attention=needs_attention,
            q=q,
            sort_by=sort_by,
            order=order,
        )

    async def needs_attention_count(self, *, viewer: User) -> int:
        return await self.repo.needs_attention_count(viewer=viewer)

    async def list_by_attention_reason(
        self, *, viewer: User, reason: str, page: int, per_page: int
    ) -> tuple[list[Conversation], int]:
        """Conversations matching an attention reason, viewer-scoped.

        Reuses ``DashboardRepository.attention_rows`` (the same predicates the
        /dashboard/attention endpoint uses) so the reason definitions stay DRY.
        Fetches BOTH immediate and today queues, filters to the requested reason,
        then resolves full Conversation rows with viewer scoping.

        Rows the dashboard surfaced with a NULL ``conversation_id`` (CALL-only,
        ``zalo_id IS NULL`` leads) are skipped here — this endpoint returns
        conversations, and those leads have no thread to open.
        """
        import uuid as _uuid

        from app.models.user import Role
        from app.services.dashboard.repository import DashboardRepository

        recruiter_id = None if viewer.role == Role.admin else str(viewer.id)
        repo = DashboardRepository(self.db)
        # Large limit to cover the full filtered set — these are bounded by real
        # attention volume, not unbounded. Both queues are fetched because a
        # reason's home queue is an implementation detail of the dashboard view;
        # the continuation must work regardless of where the row surfaced.
        immediate = await repo.attention_rows(recruiter_id, "immediate", limit=500)
        today = await repo.attention_rows(recruiter_id, "today", limit=500)
        ids: list[_uuid.UUID] = []
        for row in [*immediate, *today]:
            if row.get("reason") != reason:
                continue
            cid = row.get("conversation_id")
            if cid is None:
                continue  # CALL-only lead row, no thread to open
            ids.append(_uuid.UUID(str(cid)))
        # Dedup (a conversation can surface under multiple reasons across the two
        # queues) while preserving first-seen order for a stable inbox.
        seen: set[_uuid.UUID] = set()
        unique_ids: list[_uuid.UUID] = []
        for cid in ids:
            if cid not in seen:
                seen.add(cid)
                unique_ids.append(cid)
        total = len(unique_ids)
        start = (page - 1) * per_page
        page_ids = unique_ids[start : start + per_page]
        rows = await self.repo.get_visible_by_ids(viewer=viewer, ids=page_ids)
        # Preserve the filtered order in the returned page.
        rows_by_id = {r.id: r for r in rows}
        ordered = [rows_by_id[cid] for cid in page_ids if cid in rows_by_id]
        return ordered, total

    async def last_messages(self, conv: Conversation, limit: int = 50) -> list[Message]:
        return await self.repo.last_messages(conv, limit)

    async def latest_message(self, conv: Conversation) -> Message | None:
        return await self.repo.latest_message(conv)

    async def latest_worker_message(self, conv: Conversation) -> Message | None:
        return await self.repo.latest_worker_message(conv)

    async def messages_page(
        self, conv: Conversation, limit: int = 50, before_id: int | None = None
    ) -> list[Message]:
        return await self.repo.messages_page(conv, limit, before_id)

    async def messages_since(
        self, conv: Conversation, since_id: int | None = None, limit: int = 200
    ) -> list[Message]:
        return await self.repo.messages_since(conv, since_id, limit)

    async def latest_unanswered_worker_message(self, conv: Conversation) -> Message | None:
        return await self.repo.latest_unanswered_worker_message(conv)

    # --- mutations (delegate to state) ---
    async def ensure(self, zalo_chat_id: str, *, zalo_channel: str = "bot") -> Conversation:
        return await self.state.ensure(zalo_chat_id, zalo_channel=zalo_channel)

    def run_start_guard(self, conv: Conversation) -> bool:
        return self.state.run_start_guard(conv)

    def semi_auto_inactive(self, conv: Conversation) -> bool:
        return self.state.semi_auto_inactive(conv)

    async def record_inbound(
        self,
        conv: Conversation,
        *,
        body: str,
        zalo_message_id: str | None = None,
        runtime_revision_id: uuid.UUID | None = None,
        authority_generation: int | None = None,
        runtime_fingerprint: str | None = None,
    ) -> Message:
        return await self.state.record_inbound(
            conv,
            body=body,
            zalo_message_id=zalo_message_id,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
        )

    async def escalate_extracted_intent(
        self,
        conv: Conversation,
        *,
        reason: str,
        confidence: float,
        expected_version: int,
    ) -> bool:
        return await self.state.escalate_extracted_intent(
            conv,
            reason=reason,
            confidence=confidence,
            expected_version=expected_version,
        )

    async def acquire_lock(
        self,
        conv_id: uuid.UUID,
        ttl_seconds: int | None = None,
        lock_owner: uuid.UUID | str | None = None,
    ) -> uuid.UUID | None:
        return await self.state.acquire_lock(conv_id, ttl_seconds, lock_owner)

    async def release_lock(
        self, conv: Conversation, lock_owner: uuid.UUID | str | None = None
    ) -> None:
        await self.state.release_lock(conv, lock_owner)

    async def renew_lock(
        self, conv_id: uuid.UUID, *, lock_owner: uuid.UUID | str, ttl_seconds: int | None = None
    ) -> bool:
        return await self.state.renew_lock(conv_id, lock_owner=lock_owner, ttl_seconds=ttl_seconds)

    async def recheck_ownership(
        self,
        conv: Conversation,
        version_at_start: int,
        lock_owner: uuid.UUID | str | None = None,
    ) -> bool:
        return await self.state.recheck_ownership(conv, version_at_start, lock_owner)

    async def claim_send(
        self,
        conv: Conversation,
        *,
        version_at_start: int,
        lock_owner: uuid.UUID | str | None,
        pending_message_id: int | None,
        reply: str,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> bool:
        return await self.state.claim_send(
            conv,
            version_at_start=version_at_start,
            lock_owner=lock_owner,
            pending_message_id=pending_message_id,
            reply=reply,
            outbox_channel=outbox_channel,
            outbox_payload=outbox_payload,
        )

    async def dispatch_outbound_message(self, *, message_id: int):
        from app.services.outbox_service import dispatch_message_outbox

        return await dispatch_message_outbox(self.db, message_id=message_id)

    async def finalize_outbound_dispatch(
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
        return await self.state.finalize_outbound_dispatch(
            conv,
            message_id=message_id,
            outbox_id=outbox_id,
            delivered=delivered,
            zalo_message_id=zalo_message_id,
            external_error=external_error,
            error_class=error_class,
            suppressed=suppressed,
        )

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
        stage_timings: dict | None = None,
        lock_owner: uuid.UUID | str | None = None,
        delivery_status: DeliveryStatus | None = None,
        trace_id: str | None = None,
        outcome_metadata: dict | None = None,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> Message:
        return await self.state.record_bot_outcome(
            conv,
            version_at_start=version_at_start,
            reply=reply,
            started_at=started_at,
            sent=sent,
            pending_message_id=pending_message_id,
            external_error=external_error,
            zalo_message_id=zalo_message_id,
            stage_timings=stage_timings,
            lock_owner=lock_owner,
            delivery_status=delivery_status,
            trace_id=trace_id,
            outcome_metadata=outcome_metadata,
            outbox_channel=outbox_channel,
            outbox_payload=outbox_payload,
        )

    async def record_bot_pending(
        self,
        conv: Conversation,
        *,
        body: str = "Đang soạn trả lời...",
        runtime_revision_id: uuid.UUID | None = None,
        authority_generation: int | None = None,
        runtime_fingerprint: str | None = None,
    ) -> Message:
        return await self.state.record_bot_pending(
            conv,
            body=body,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
        )

    async def take_over(self, conv: Conversation, recruiter: User) -> Conversation:
        return await self.state.take_over(conv, recruiter)

    async def release(self, conv: Conversation, actor: User) -> Conversation:
        return await self.state.release(conv, actor)

    async def semi_auto(self, conv: Conversation, recruiter: User) -> Conversation:
        return await self.state.semi_auto(conv, recruiter)

    async def close(self, conv: Conversation, actor: User) -> Conversation:
        return await self.state.close(conv, actor)

    async def reopen(self, conv: Conversation, actor: User) -> Conversation:
        return await self.state.reopen(conv, actor)

    async def clear_history(self, conv: Conversation, actor: User) -> Conversation:
        return await self.state.clear_history(conv, actor)

    async def delete(self, conv: Conversation, actor: User) -> None:
        await self.state.delete(conv, actor)

    async def mark_read(self, conv: Conversation) -> Conversation:
        return await self.state.mark_read(conv)

    async def record_recruiter_message(
        self, conv: Conversation, recruiter: User, body: str, result: SendResult
    ) -> Message:
        return await self.state.record_recruiter_message(conv, recruiter, body, result)

    async def record_proactive_outcome(
        self,
        conv: Conversation,
        *,
        message: str,
        result: SendResult,
        lock_owner: uuid.UUID | str | None = None,
        pending_message_id: int | None = None,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> Message:
        return await self.state.record_proactive_outcome(
            conv,
            message=message,
            result=result,
            lock_owner=lock_owner,
            pending_message_id=pending_message_id,
            outbox_channel=outbox_channel,
            outbox_payload=outbox_payload,
        )

    async def prepare_proactive_message(
        self,
        conv: Conversation,
        *,
        body: str,
        channel: str,
        payload: dict,
    ) -> Message:
        return await self.state.prepare_proactive_message(
            conv, body=body, channel=channel, payload=payload
        )

    async def apply_delivery_receipt(
        self,
        conv: Conversation,
        *,
        zalo_message_id: str | None,
        delivered: bool = False,
        seen: bool = False,
    ) -> bool:
        return await self.state.apply_delivery_receipt(
            conv,
            zalo_message_id=zalo_message_id,
            delivered=delivered,
            seen=seen,
        )

    async def apply_delivery_receipt_batch(
        self,
        conv: Conversation,
        *,
        zalo_message_ids: list[str],
        delivered: bool = False,
        seen: bool = False,
    ) -> int:
        return await self.state.apply_delivery_receipt_batch(
            conv,
            zalo_message_ids=zalo_message_ids,
            delivered=delivered,
            seen=seen,
        )

    async def record_system_note(self, conv: Conversation, *, body: str) -> Message:
        return await self.state.record_system_note(conv, body=body)

    async def apply_follow(self, conv: Conversation) -> Conversation:
        return await self.state.apply_follow(conv)

    async def apply_unfollow(self, conv: Conversation) -> Conversation:
        return await self.state.apply_unfollow(conv)

    async def deliver_recruiter_message(
        self, conv: Conversation, recruiter: User, body: str
    ) -> tuple[Message, bool]:
        """Persist then immediately dispatch a recruiter reply via the shared outbox."""
        from app.services.errors import DeliveryEligibilityError
        from app.services.outbox_service import build_outbox_payload, dispatch_outbox

        quote_message_id = None
        is_oa = (getattr(conv, "zalo_channel", None) or "bot") == "oa"
        if is_oa:
            latest_inbound = await self.latest_worker_message(conv)
            quote_message_id = latest_inbound.zalo_message_id if latest_inbound else None
            if not quote_message_id:
                raise DeliveryEligibilityError(
                    "Không thể gửi tin Zalo vì chưa có tin nhắn của ứng viên để phản hồi."
                )
        msg, outbox_id = await self.state.prepare_recruiter_message(
            conv,
            recruiter,
            body=body,
            channel="zalo_oa" if is_oa else "zalo_bot",
            payload=build_outbox_payload(conv.zalo_chat_id, body, quote_message_id),
        )
        attempt = await dispatch_outbox(self.db, outbox_id=outbox_id)
        if attempt is None:
            return msg, False
        msg = await self.state.finalize_recruiter_delivery(
            conv,
            message_id=attempt.message_id,
            outbox_id=attempt.outbox_id,
            delivered=attempt.ok,
            zalo_message_id=attempt.zalo_message_id,
            external_error=attempt.error,
            error_class=attempt.error_class,
        )
        return msg, attempt.ok

    async def retry_recruiter_message(
        self, conv: Conversation, *, message_id: int
    ) -> tuple[Message | None, bool]:
        """Retry one known failed recruiter message without creating a new row."""
        from app.models.conversation import Message
        from app.services.outbox_service import dispatch_outbox

        outbox_id = await self.state.retry_recruiter_message(conv, message_id=message_id)
        if outbox_id is None:
            return None, False
        attempt = await dispatch_outbox(self.db, outbox_id=outbox_id)
        if attempt is None:
            return await self.db.get(Message, message_id), False
        msg = await self.state.finalize_recruiter_delivery(
            conv,
            message_id=attempt.message_id,
            outbox_id=attempt.outbox_id,
            delivered=attempt.ok,
            zalo_message_id=attempt.zalo_message_id,
            external_error=attempt.error,
            error_class=attempt.error_class,
        )
        return msg, attempt.ok

    async def release_and_enqueue_unanswered(
        self,
        conv: Conversation,
        actor: User,
        *,
        enqueue: Callable[..., object],
    ) -> Conversation:
        """Release a conversation to BOT mode and schedule any pending worker reply."""
        released = await self.release(conv, actor)
        await enqueue_latest_unanswered_worker_message(self, released, enqueue=enqueue)
        return released
