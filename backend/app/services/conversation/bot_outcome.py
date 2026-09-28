"""Bot-run and BOT-message outcome recording for the bot-send path.

Records the durable outcome of a bot turn (the run row, the message row, the
lock release, and the transactional-outbox receipt) plus the visible pending
placeholder and its stale-predecessor cleanup. Mixed into
``BotConversationState``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid
from datetime import datetime

from sqlalchemy import update

from app.conversation_messaging.domain.delivery import delivery_rank
from app.conversation_messaging.domain.ownership import (
    normalize_lock_owner as _normalize_lock_owner,
)
from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    Conversation,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.schemas.bot_run import parse_decision_trace
from app.services.conversation._shared import affected_rows, utcnow



if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.conversation_messaging.application.ports import ConversationEventsPort

class BotOutcomeMixin:
    """bot_run + BOT message outcome recording."""

    # Assigned by the composing state class. Declared so ``self.db``
    # resolves here — the mixin reads it but never owns it.
    db: AsyncSession
    events: ConversationEventsPort

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
        """Log a bot_run + BOT message; clears the lock.

        ``sent=False`` means either ownership suppression or delivery failure.
        ``external_error`` disambiguates real send failures so recovery can
        retry them instead of treating them as completed suppressed turns.

        ``delivery_status`` overrides the computed status. Used by the send path
        to stamp ``SEND_UNKNOWN`` when a transport exception may have reached
        Zalo (non-retriable — the reconciler skips these). When None, the status
        is derived from ``sent``/``external_error`` as before (backward compat).

        ``stage_timings`` is the per-stage wall-clock dict captured by run_turn
        (webhook_to_pickup / preamble / lane / lead / llm / safety / send /
        total). Persisted onto the BotRun for the performance dashboard; None
        on paths that don't instrument (e.g. legacy callers).

        ``outbox_channel`` + ``outbox_payload``: when both provided, an
        ``outbound_outbox`` row is written in THIS transaction (Tech-Lead
        Directive §14) so the outbox reflects the committed send outcome
        atomically. The channel is the canonical provider id and the payload is
        the immutable provider send body. Best-effort — outbox failures never
        block the turn.
        """
        if delivery_status is None:
            delivery_status = (
                DeliveryStatus.FAILED
                if external_error
                else DeliveryStatus.SENT
                if sent
                else DeliveryStatus.SUPPRESSED
            )
        outcome = (
            BotRunOutcome.SUPPRESSED
            if delivery_status == DeliveryStatus.SUPPRESSED
            else BotRunOutcome.ERROR
            if external_error
            else BotRunOutcome.SENT
            if sent
            else BotRunOutcome.SUPPRESSED
        )
        parsed_trace = parse_decision_trace(decision_trace)
        safe_decision_trace = (
            parsed_trace.model_dump(mode="json") if parsed_trace is not None else None
        )
        run = BotRun(
            conversation_id=conv.id,
            version_at_start=version_at_start,
            proposed_reply=reply,
            outcome=outcome,
            started_at=started_at,
            ended_at=utcnow(),
            stage_timings=stage_timings,
            trace_id=trace_id or None,
            outcome_metadata=outcome_metadata,
            decision_trace=safe_decision_trace,
        )
        msg = None
        pending_msg = None
        matched_pending = False
        resolved_delivery_status = delivery_status
        if pending_message_id is not None:
            pending_msg = await self.db.get(
                Message,
                pending_message_id,
                with_for_update=True,
            )
            if (
                pending_msg is not None
                and pending_msg.conversation_id == conv.id
                and pending_msg.sender == MessageSender.BOT
                and pending_msg.delivery_status
                in (
                    DeliveryStatus.PENDING,
                    DeliveryStatus.SENDING,
                    DeliveryStatus.SEND_UNKNOWN,
                    DeliveryStatus.SENT,
                    DeliveryStatus.DELIVERED,
                    DeliveryStatus.READ,
                )
            ):
                matched_pending = True
                run.runtime_revision_id = pending_msg.runtime_revision_id
                run.authority_generation = pending_msg.authority_generation
                run.runtime_fingerprint = pending_msg.runtime_fingerprint
        self.db.add(run)
        await self.db.flush()
        if matched_pending and pending_msg is not None:
            resolved_delivery_status = (
                pending_msg.delivery_status
                if delivery_rank(pending_msg.delivery_status)
                > delivery_rank(delivery_status)
                else delivery_status
            )
            pending_msg.body = reply
            pending_msg.bot_run_id = run.id
            pending_msg.delivery_status = resolved_delivery_status
            pending_msg.external_error = (
                None
                if delivery_rank(resolved_delivery_status)
                >= delivery_rank(DeliveryStatus.SENT)
                else external_error
            )
            if zalo_message_id:
                pending_msg.zalo_message_id = zalo_message_id
                pending_msg.provider_message_id = zalo_message_id
            msg = pending_msg
        if msg is None:
            msg = Message(
                conversation_id=conv.id,
                sender=MessageSender.BOT,
                body=reply,
                bot_run_id=run.id,
                delivery_status=delivery_status,
                external_error=external_error,
                zalo_message_id=zalo_message_id,
                provider_message_id=zalo_message_id,
            )
            self.db.add(msg)
        owner = _normalize_lock_owner(lock_owner)
        if owner is None:
            conv.bot_locked_until = None
            conv.bot_lock_owner = None
            conv.bot_lock_heartbeat_at = None
        else:
            clear_res = await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conv.id, Conversation.bot_lock_owner == owner)
                .values(
                    bot_locked_until=None,
                    bot_lock_owner=None,
                    bot_lock_heartbeat_at=None,
                    conversation_seq=Conversation.conversation_seq + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if affected_rows(clear_res) == 1:
                conv.bot_locked_until = None
                conv.bot_lock_owner = None
                conv.bot_lock_heartbeat_at = None
        if delivery_rank(resolved_delivery_status) >= delivery_rank(
            DeliveryStatus.SENT
        ):
            conv.last_outbound_at = utcnow()
        # Bump the strict monotonic seq for every bot outcome (the key delta vs
        # `version`, which intentionally skips bot outcomes). The no-owner branch
        # touches conv in Python below; the owner branch bumped via SQL above.
        if owner is None:
            conv.conversation_seq = (conv.conversation_seq or 1) + 1
        # Transactional outbox (Tech-Lead Directive §14): record the dispatch
        # outcome in the same transaction as the message. Best-effort — outbox
        # failures never block the turn (logged in outbox_service).
        outbox_attempts = 0
        if outbox_channel is not None and outbox_payload is not None and msg.id is not None:
            from app.models.outbox import OutboxStatus
            from app.services.outbox_service import enqueue_outbox

            outbox_status = (
                OutboxStatus.SENT
                if delivery_rank(resolved_delivery_status)
                >= delivery_rank(DeliveryStatus.SENT)
                else OutboxStatus.SEND_UNKNOWN
                if resolved_delivery_status == DeliveryStatus.SEND_UNKNOWN
                else OutboxStatus.FAILED
                if resolved_delivery_status == DeliveryStatus.FAILED
                else OutboxStatus.SUPPRESSED
            )
            outbox = await enqueue_outbox(
                self.db,
                message_id=msg.id,
                channel=outbox_channel,
                payload=outbox_payload,
                status=outbox_status,
                zalo_message_id=msg.zalo_message_id,
                provider_message_id=msg.provider_message_id,
                last_error=msg.external_error,
                runtime_revision_id=msg.runtime_revision_id,
                authority_generation=msg.authority_generation,
                runtime_fingerprint=msg.runtime_fingerprint,
                origin_kind="BOT" if msg.runtime_revision_id is not None else None,
                fence_scope="RUNTIME" if msg.runtime_revision_id is not None else None,
            )
            if outbox is not None:
                outbox_attempts = int(outbox.attempts or 0)
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox_attempts
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def record_bot_pending(
        self,
        conv: Conversation,
        *,
        body: str = "Đang soạn trả lời...",
        runtime_revision_id: uuid.UUID | None = None,
        authority_generation: int | None = None,
        runtime_fingerprint: str | None = None,
    ) -> Message:
        """Persist a visible pending BOT row without touching the version guard.

        Any BOT/PENDING row still open for this conversation belongs to a
        predecessor that died without a terminal write (SIGKILL/OOM, worker
        shutdown) — the caller reaches this only while holding the per-chat
        mutex (``run_turn`` rechecks ownership first), so no live turn can own
        one. Resolving it here keeps exactly one live placeholder per
        conversation instead of leaving an orphaned "Đang soạn trả lời..." bubble
        stranded behind the new one.
        """
        await self.mark_stale_pending_failed(conv.id)
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.BOT,
            body=body,
            delivery_status=DeliveryStatus.PENDING,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        # Realtime fan-out is deferred (fire-and-forget): payloads are serialized
        # eagerly on this coroutine (ORM attrs are expired post-commit and must
        # not be touched from the background task) and only the Redis publishes
        # run on it. See ConversationEventBus.schedule_realtime.
        self.events.schedule_realtime(msg, conv)
        return msg

    async def mark_stale_pending_failed(self, conv_id: uuid.UUID) -> int:
        """Flip any BOT/PENDING message rows for this conversation to FAILED.

        Call ONLY after ``acquire_lock()`` succeeded, so no live turn owns these
        rows.  Returns the number of rows updated.  No version bump, no
        ``last_outbound_at`` change, no events — the PENDING placeholder is
        ephemeral UI chrome that a crashed turn left behind.
        """
        res = await self.db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.BOT,
                Message.delivery_status == DeliveryStatus.PENDING,
            )
            .values(delivery_status=DeliveryStatus.FAILED)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return affected_rows(res)
