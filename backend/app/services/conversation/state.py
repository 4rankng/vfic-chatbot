"""Conversation state mutations + orchestration (the takeover race-guard core).

This module is the composed public type of the conversation state layer: it
keeps the full pre-split surface — import stability for every caller — while
delegating each method to the internal half that owns it:

- ``bot_path.BotConversationState`` — bot-send path: webhook-side primitives,
  inbound guards, intent escalation, per-chat locking, the TOCTOU send claim,
  bot outcomes, reconcile sweeps, proactive follow-up.
- ``recruiter_path.RecruiterMessagingState`` — recruiter messaging: lifecycle
  transitions, human replies, delivery finalization, receipts, notes/follow.

All state changes bump ``version`` (the optimistic-lock token) and fan out a realtime
event via the event bus.

Reads live in ``repository.py``; realtime publishing in ``events.py``; private
helpers shared by both halves (and the single owner of the delivery-status
derivation) in ``_shared.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.conversation_messaging.application.ports import (
    ConversationEventsPort,
    DeliveryResultPort,
)
from app.models.conversation import Conversation, DeliveryStatus, Message
from app.models.user import User
from app.services.conversation._shared import utcnow
from app.services.conversation.bot_path import BotConversationState
from app.services.conversation.recruiter_path import (
    ConversationConflict,
    RecruiterMessagingState,
)
from app.shared.application.outbound import OutboundTelemetry

__all__ = ["ConversationConflict", "ConversationState", "utcnow"]


class ConversationState:
    """Mutates conversation/message rows + records audit + publishes realtime events.

    Composed public type: keeps the full pre-split surface (import stability —
    callers and tests construct it directly with (db, repo, events)) while
    delegating each method to the internal half that owns it — ``self._bot``
    (bot-send path) or ``self._recruiter`` (recruiter messaging).
    """

    def __init__(self, db, repo, events: ConversationEventsPort) -> None:
        self.db = db
        self.repo = repo
        self.events = events
        self._bot = BotConversationState(db, repo, events)
        self._recruiter = RecruiterMessagingState(db, events)


    async def ensure(
        self,
        zalo_chat_id: str,
        *,
        zalo_channel: str = "bot",
        account_key: str | None = None,
    ) -> Conversation:
        return await self._bot.ensure(
            zalo_chat_id,
            zalo_channel=zalo_channel,
            account_key=account_key,
        )

    async def ensure_by_identity(
        self,
        *,
        provider: str,
        account_key: str,
        external_id: str,
        zalo_chat_id_alias: str | None = None,
        zalo_channel_alias: str | None = None,
    ) -> Conversation:
        return await self._bot.ensure_by_identity(
            provider=provider,
            account_key=account_key,
            external_id=external_id,
            zalo_chat_id_alias=zalo_chat_id_alias,
            zalo_channel_alias=zalo_channel_alias,
        )

    def semi_auto_inactive(
        self,
        conv: Conversation,
    ) -> bool:
        return self._bot.semi_auto_inactive(
            conv,
        )

    def run_start_guard(
        self,
        conv: Conversation,
    ) -> bool:
        return self._bot.run_start_guard(
            conv,
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
        return await self._bot.record_inbound(
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
        return await self._bot.escalate_extracted_intent(
            conv,
            reason=reason,
            confidence=confidence,
            expected_version=expected_version,
            preserve_turn_ownership=preserve_turn_ownership,
        )

    async def acquire_lock(
        self,
        conv_id: uuid.UUID,
        ttl_seconds: int | None = None,
        lock_owner: uuid.UUID | str | None = None,
    ) -> uuid.UUID | None:
        return await self._bot.acquire_lock(
            conv_id,
            ttl_seconds,
            lock_owner,
        )

    async def release_lock(
        self,
        conv: Conversation,
        lock_owner: uuid.UUID | str | None = None,
    ) -> None:
        await self._bot.release_lock(
            conv,
            lock_owner,
        )

    async def renew_lock(
        self,
        conv_id: uuid.UUID,
        *,
        lock_owner: uuid.UUID | str,
        ttl_seconds: int | None = None,
    ) -> bool:
        return await self._bot.renew_lock(
            conv_id,
            lock_owner=lock_owner,
            ttl_seconds=ttl_seconds,
        )

    async def break_stale_lock(
        self,
        conv_id: uuid.UUID,
        *,
        stale_after_seconds: int,
    ) -> bool:
        return await self._bot.break_stale_lock(
            conv_id,
            stale_after_seconds=stale_after_seconds,
        )

    async def recheck_ownership(
        self,
        conv: Conversation,
        version_at_start: int,
        lock_owner: uuid.UUID | str | None = None,
    ) -> bool:
        return await self._bot.recheck_ownership(
            conv,
            version_at_start,
            lock_owner,
        )

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
        return await self._bot.claim_send(
            conv,
            version_at_start=version_at_start,
            lock_owner=lock_owner,
            pending_message_id=pending_message_id,
            reply=reply,
            outbox_channel=outbox_channel,
            outbox_payload=outbox_payload,
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
        return await self._bot.record_bot_outcome(
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
        return await self._bot.record_bot_pending(
            conv,
            body=body,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
        )

    async def mark_stale_pending_failed(
        self,
        conv_id: uuid.UUID,
    ) -> int:
        return await self._bot.mark_stale_pending_failed(
            conv_id,
        )

    async def resolve_unconfirmed_sending(
        self,
        conv_id: uuid.UUID,
    ) -> int:
        return await self._bot.resolve_unconfirmed_sending(
            conv_id,
        )

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
        return await self._bot.record_proactive_outcome(
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
        return await self._bot.prepare_proactive_message(
            conv,
            body=body,
            channel=channel,
            payload=payload,
        )

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
        return await self._bot.finalize_outbound_dispatch(
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

    async def take_over(
        self,
        conv: Conversation,
        recruiter: User,
    ) -> Conversation:
        return await self._recruiter.take_over(
            conv,
            recruiter,
        )

    async def release(
        self,
        conv: Conversation,
        actor: User,
    ) -> Conversation:
        return await self._recruiter.release(
            conv,
            actor,
        )

    async def semi_auto(
        self,
        conv: Conversation,
        recruiter: User,
    ) -> Conversation:
        return await self._recruiter.semi_auto(
            conv,
            recruiter,
        )

    async def close(
        self,
        conv: Conversation,
        actor: User,
    ) -> Conversation:
        return await self._recruiter.close(
            conv,
            actor,
        )

    async def reopen(
        self,
        conv: Conversation,
        actor: User,
    ) -> Conversation:
        return await self._recruiter.reopen(
            conv,
            actor,
        )

    async def clear_history(
        self,
        conv: Conversation,
        actor: User,
    ) -> Conversation:
        return await self._recruiter.clear_history(
            conv,
            actor,
        )

    async def delete(
        self,
        conv: Conversation,
        actor: User,
    ) -> None:
        await self._recruiter.delete(
            conv,
            actor,
        )

    async def mark_read(
        self,
        conv: Conversation,
    ) -> Conversation:
        return await self._recruiter.mark_read(
            conv,
        )

    async def record_recruiter_message(
        self,
        conv: Conversation,
        recruiter: User,
        body: str,
        result: DeliveryResultPort,
    ) -> Message:
        return await self._recruiter.record_recruiter_message(
            conv,
            recruiter,
            body,
            result,
        )

    async def prepare_recruiter_message(
        self,
        conv: Conversation,
        recruiter: User,
        *,
        body: str,
        channel: str,
        payload: dict,
    ) -> tuple[Message, int]:
        return await self._recruiter.prepare_recruiter_message(
            conv,
            recruiter,
            body=body,
            channel=channel,
            payload=payload,
        )

    async def finalize_recruiter_delivery(
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
        return await self._recruiter.finalize_recruiter_delivery(
            conv,
            message_id=message_id,
            outbox_id=outbox_id,
            delivered=delivered,
            zalo_message_id=zalo_message_id,
            external_error=external_error,
            error_class=error_class,
            suppressed=suppressed,
        )

    async def retry_recruiter_message(
        self,
        conv: Conversation,
        *,
        message_id: int,
    ) -> int | None:
        return await self._recruiter.retry_recruiter_message(
            conv,
            message_id=message_id,
        )

    async def apply_delivery_receipt(
        self,
        conv: Conversation,
        *,
        zalo_message_id: str | None,
        delivered: bool = False,
        seen: bool = False,
    ) -> bool:
        return await self._recruiter.apply_delivery_receipt(
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
        return await self._recruiter.apply_delivery_receipt_batch(
            conv,
            zalo_message_ids=zalo_message_ids,
            delivered=delivered,
            seen=seen,
        )

    async def record_system_note(
        self,
        conv: Conversation,
        *,
        body: str,
    ) -> Message:
        return await self._recruiter.record_system_note(
            conv,
            body=body,
        )

    async def apply_follow(
        self,
        conv: Conversation,
    ) -> Conversation:
        return await self._recruiter.apply_follow(
            conv,
        )

    async def apply_unfollow(
        self,
        conv: Conversation,
    ) -> Conversation:
        return await self._recruiter.apply_unfollow(
            conv,
        )
