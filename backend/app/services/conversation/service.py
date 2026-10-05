"""``ConversationService`` — the composed conversation facade.

Composes :class:`~app.services.conversation.repository.ConversationRepository`
(reads), :class:`~app.services.conversation.events.ConversationEventBus`
(realtime publishing) and :class:`~app.services.conversation.state.ConversationState`
(mutations + orchestration). ``db``/``repo``/``events``/``state`` are public:
a caller that knows which part it means reaches for that part directly
(``svc.state.take_over`` , ``svc.repo.list``) instead of through a forwarder.

What stays here is only the surface that has no single owning part:

* the narrowed set the graph brain consumes through
  ``graph/ports.ConversationPort`` (lock lifecycle, send claim, bot outcomes,
  pending/outbound dispatch), plus the ingress primitives the provider-neutral
  adapters call;
* the cross-part orchestrations — ``deliver_recruiter_message``,
  ``retry_recruiter_message``, ``release_and_enqueue_unanswered`` — which are
  behaviour, not delegation.

``claim_send`` delegates to ``state.claim_send``; that target is a verified
atomic seam and must not be re-pointed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.chat_status import fire_preparation_chat_status
from app.services.conversation.events import ConversationEventBus
from app.services.conversation.repository import ConversationRepository
from app.services.conversation.scheduler import enqueue_latest_unanswered_worker_message
from app.services.conversation.state import ConversationState

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from datetime import datetime

    from app.models.conversation import Conversation, DeliveryStatus, Message
    from app.models.user import User
    from app.shared.application.outbound import OutboundTelemetry

__all__ = ["ConversationService"]


class ConversationService:
    def __init__(self, db) -> None:
        self.db = db
        self.repo = ConversationRepository(db)
        self.events = ConversationEventBus(db)
        self.state = ConversationState(db, self.repo, self.events)

    # --- reads (delegate to repository) ---

    async def get(self, conv_id: uuid.UUID) -> Conversation | None:
        return await self.repo.get(conv_id)

    async def get_by_zalo(self, zalo_chat_id: str) -> Conversation | None:
        return await self.repo.get_by_zalo(zalo_chat_id)

    async def get_by_identity(
        self, *, provider: str, account_key: str, external_id: str
    ) -> Conversation | None:
        return await self.repo.get_by_identity(
            provider=provider, account_key=account_key, external_id=external_id
        )

    async def last_messages(self, conv: Conversation, limit: int = 50) -> list[Message]:
        return await self.repo.last_messages(conv, limit)

    async def latest_unanswered_worker_message(self, conv: Conversation) -> Message | None:
        return await self.repo.latest_unanswered_worker_message(conv)

    # --- ingress primitives (delegate to state) ---

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
        preserve_turn_ownership: bool = False,
    ) -> bool:
        return await self.state.escalate_extracted_intent(
            conv,
            reason=reason,
            confidence=confidence,
            expected_version=expected_version,
            preserve_turn_ownership=preserve_turn_ownership,
        )

    # --- per-chat lock lifecycle (the graph port's surface) ---

    def run_start_guard(self, conv: Conversation) -> bool:
        return self.state.run_start_guard(conv)

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

    async def recheck_ownership(
        self,
        conv: Conversation,
        version_at_start: int,
        lock_owner: uuid.UUID | str | None = None,
    ) -> bool:
        return await self.state.recheck_ownership(conv, version_at_start, lock_owner)

    # --- the turn's send claim + durable outbound command ---

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

    # --- bot turn outcomes ---

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

    # --- cross-part orchestrations (behaviour, not delegation) ---

    async def deliver_recruiter_message(
        self, conv: Conversation, recruiter: User, body: str
    ) -> tuple[Message, bool]:
        """Persist then immediately dispatch a recruiter reply via the shared outbox."""
        from app.recruitment.domain.provider import (
            provider_from_conversation,
            recipient_from_conversation,
        )
        from app.services.outbox_service import build_outbox_payload, dispatch_outbox
        from app.shared.domain.errors import DeliveryEligibilityError

        quote_message_id = None
        channel = provider_from_conversation(conv)
        recipient_id = recipient_from_conversation(conv)
        if not recipient_id:
            # Mirror of the graph-side send guard: a conversation that lost its
            # chat id must not persist an outbox row addressed to ``None``.
            raise DeliveryEligibilityError(
                "Không thể gửi tin vì cuộc trò chuyện không có người nhận."
            )
        is_oa = channel == "zalo_oa"
        if is_oa:
            latest_inbound = await self.repo.latest_worker_message(conv)
            quote_message_id = latest_inbound.zalo_message_id if latest_inbound else None
            if not quote_message_id:
                raise DeliveryEligibilityError(
                    "Không thể gửi tin Zalo vì chưa có tin nhắn của ứng viên để phản hồi."
                )
        # Native Zalo chat status while the app prepares this message: one
        # temporary "typing" pulse before the prepare/dispatch window opens.
        # Bot channel only — OA and Messenger carry no typing operation.
        await fire_preparation_chat_status(
            self.db, channel=channel, recipient_id=recipient_id
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
        from app.recruitment.domain.provider import (
            provider_from_conversation,
            recipient_from_conversation,
        )
        from app.services.outbox_service import dispatch_outbox

        # Same preparation window as a fresh reply: the candidate sees the
        # temporary Zalo status before the re-armed command reaches the wire.
        await fire_preparation_chat_status(
            self.db,
            channel=provider_from_conversation(conv),
            recipient_id=recipient_from_conversation(conv),
        )
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
        enqueue: Callable[[dict], bool | None],
    ) -> Conversation:
        """Release a conversation to BOT mode and schedule any pending worker reply."""
        released = await self.state.release(conv, actor)
        await enqueue_latest_unanswered_worker_message(self, released, enqueue=enqueue)
        return released
