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

    async def last_messages(self, conv: Conversation, limit: int = 50) -> list[Message]:
        return await self.repo.last_messages(conv, limit)

    async def latest_message(self, conv: Conversation) -> Message | None:
        return await self.repo.latest_message(conv)

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
    ) -> Message:
        return await self.state.record_inbound(conv, body=body, zalo_message_id=zalo_message_id)

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
    ) -> bool:
        return await self.state.claim_send(
            conv,
            version_at_start=version_at_start,
            lock_owner=lock_owner,
            pending_message_id=pending_message_id,
            reply=reply,
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
        )

    async def record_bot_pending(
        self, conv: Conversation, *, body: str = "Đang soạn trả lời..."
    ) -> Message:
        return await self.state.record_bot_pending(conv, body=body)

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
    ) -> Message:
        return await self.state.record_proactive_outcome(
            conv, message=message, result=result, lock_owner=lock_owner
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
        """Send a recruiter reply via Zalo + record it. Returns ``(message, delivered_ok)``.

        Owns the ``ZaloBotSender`` instantiation so the router stays free of the external
        client. The sender is imported lazily to keep the web-process import path free of
        httpx/external deps at module load. ``record_recruiter_message`` (state) stays a
        decoupled, testable pure-persist that takes the send result as a param.
        """
        from app.services.integration_settings import IntegrationSettingsService
        from app.services.zalo_sender import ZaloChannelSender

        integration_settings = IntegrationSettingsService(self.db)
        cfg = await integration_settings.resolve_zalo()
        sender = ZaloChannelSender(
            cfg, refresh=lambda: integration_settings.refresh_oa_access_token()
        ).for_conversation(conv)
        result = await sender.send_message(conv.zalo_chat_id, body)
        msg = await self.state.record_recruiter_message(conv, recruiter, body, result)
        return msg, result.ok

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
