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
    from app.conversation_messaging.application.ports import DeliveryResultPort
    from app.shared.application.outbound import OutboundTelemetry

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

    async def get_by_identity(
        self, *, provider: str, account_key: str, external_id: str
    ) -> Conversation | None:
        return await self.repo.get_by_identity(
            provider=provider, account_key=account_key, external_id=external_id
        )

    async def last_messages_batch(self, *, viewer: User, ids_str: str) -> dict[str, str]:
        return await self.repo.last_messages_batch(viewer=viewer, ids_str=ids_str)

    async def list_by_zalo_ids(
        self,
        *,
        viewer: User,
        zalo_chat_ids: list[str],
    ) -> list[Conversation]:
        return await self.repo.list_by_zalo_ids(
            viewer=viewer,
            zalo_chat_ids=zalo_chat_ids,
        )

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
        return await self.repo.list(
            viewer=viewer,
            page=page,
            per_page=per_page,
            mode=mode,
            status=status,
            zalo_chat_id=zalo_chat_id,
            needs_attention=needs_attention,
            channel_provider=channel_provider,
            q=q,
            sort_by=sort_by,
            order=order,
        )

    async def needs_attention_count(
        self, *, viewer: User, channel_provider: str | None = None
    ) -> int:
        return await self.repo.needs_attention_count(
            viewer=viewer, channel_provider=channel_provider
        )

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

    async def ensure_by_identity(
        self,
        *,
        provider: str,
        account_key: str,
        external_id: str,
        zalo_chat_id_alias: str | None = None,
        zalo_channel_alias: str | None = None,
    ) -> Conversation:
        """Provider-neutral create-or-fetch, used by the shared ingress adapter.

        The Zalo webhook reaches state through ``ensure``; Messenger arrives
        here with a real (provider, page id, PSID) triple.
        """
        return await self.state.ensure_by_identity(
            provider=provider,
            account_key=account_key,
            external_id=external_id,
            zalo_chat_id_alias=zalo_chat_id_alias,
            zalo_channel_alias=zalo_channel_alias,
        )

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
        provider_message_id: str | None = None,
        runtime_revision_id: uuid.UUID | None = None,
        authority_generation: int | None = None,
        runtime_fingerprint: str | None = None,
    ) -> Message:
        return await self.state.record_inbound(
            conv,
            body=body,
            zalo_message_id=zalo_message_id,
            provider_message_id=provider_message_id,
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
        telemetry: OutboundTelemetry | None = None,
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
            telemetry=telemetry,
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
        decision_trace: dict | None = None,
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
            decision_trace=decision_trace,
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
        self, conv: Conversation, recruiter: User, body: str, result: DeliveryResultPort
    ) -> Message:
        return await self.state.record_recruiter_message(conv, recruiter, body, result)

    async def record_proactive_outcome(
        self,
        conv: Conversation,
        *,
        message: str,
        result: DeliveryResultPort,
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
        from app.shared.domain.errors import DeliveryEligibilityError
        from app.recruitment.domain.provider import (
            provider_from_conversation,
            recipient_from_conversation,
        )
        from app.services.outbox_service import build_outbox_payload, dispatch_outbox

        quote_message_id = None
        channel = provider_from_conversation(conv)
        recipient_id = recipient_from_conversation(conv)
        is_oa = channel == "zalo_oa"
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
            channel=channel,
            payload=build_outbox_payload(recipient_id, body, quote_message_id),
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
            suppressed=attempt.suppressed,
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
            suppressed=attempt.suppressed,
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
