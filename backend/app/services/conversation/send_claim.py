"""The TOCTOU send claim and durable-command finalization for the bot path.

``recheck_ownership`` is the pre-send guard; ``claim_send`` is the atomic
PENDING→SENDING claim that closes the recheck→send window; and
``finalize_outbound_dispatch`` writes the terminal outcome of a recovered
command. Mixed into ``BotConversationState``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

from sqlalchemy import or_, text, update

from app.conversation_messaging.domain.ownership import (
    lock_owner_matches as _lock_owner_matches,
    lock_still_live as _lock_still_live,
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
from app.services.conversation._shared import (
    _delivery_status_for_send_error,
    utcnow,
    affected_rows,
)
from app.services.conversation.unreachable import (
    USER_UNREACHABLE_SEND_CLASS,
    apply_user_unreachable_side_effects,
)
from app.shared.application.outbound import OutboundTelemetry



if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.conversation_messaging.application.ports import ConversationEventsPort

class SendClaimMixin:
    """Ownership recheck, the atomic send claim, and command finalization."""

    # Assigned by the composing state class. Declared so ``self.db``
    # resolves here — the mixin reads it but never owns it.
    db: AsyncSession
    events: ConversationEventsPort

    def run_start_guard(self, conv: Conversation) -> bool:
        """Provided by the composing state class, which owns the mode policy."""
        raise NotImplementedError

    async def recheck_ownership(
        self,
        conv: Conversation,
        version_at_start: int,
        lock_owner: uuid.UUID | str | None = None,
    ) -> bool:
        """Pre-send guard: bot may send only if eligible and version unchanged.

        IMPORTANT: the caller **must** refresh the conversation's ownership
        columns immediately before calling this method (``expire_on_commit=False``
        means the identity map hides concurrent takeovers).  The runner does a
        column-scoped ``db.refresh(conv, _OWNERSHIP_REFRESH_COLUMNS)`` covering
        everything this guard reads (``version``, ``mode``, ``status``,
        ``taken_over_at``/``updated_at`` for the semi-auto branch, and the
        ``bot_lock_*`` trio); a plain attribute read after a stale snapshot may
        approve a send after a takeover.
        """
        if not self.run_start_guard(conv) or conv.version != version_at_start:
            return False
        if lock_owner is None:
            return True
        return _lock_owner_matches(conv.bot_lock_owner, lock_owner) and _lock_still_live(
            conv.bot_locked_until
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
        """Atomically claim the outbound send: flip the pending BOT row
        PENDING→SENDING (and stamp the real ``reply`` onto it) only if the
        conversation is still bot-owned at ``version_at_start`` with a live lock
        owned by ``lock_owner``.

        This is the pre-send gate that closes both the crash-window and the
        recheck→send TOCTOU in one conditional write: the claim commits only when
        the conversation ``version`` + lock ownership + lock liveness all still
        hold, so a recruiter takeover (clears ``bot_lock_owner``) or a newer
        inbound/recruiter reply (bumps ``version``) landing before the claim
        yields rowcount 0 and the caller suppresses instead of sending. The
        authoritative guard is the ``WHERE EXISTS`` below, evaluated server-side
        at commit time, so a stale identity-map snapshot cannot race it.

        The residual window after a successful claim is [claim-commit → Zalo
        POST], irreducible without a provider idempotency key (Zalo Bot Platform
        has none); a crash there leaves a SENDING row whose body is already the
        real reply (stamped here), so the reconcile sweep can resolve it as
        sent-but-unconfirmed (at-most-once) with correct content rather than
        re-enqueuing a duplicate or persisting the placeholder. Returns True iff
        the row was claimed.

        The command is written already-SENDING for the same reason (REL-06): the
        dispatcher sweep must never see a claimable row for a send this
        transaction is about to run inline.
        """
        if pending_message_id is None or lock_owner is None:
            # The atomic claim requires both a pending BOT row to flip and a lock
            # owner to gate on. Real turns always hold both (the webhook/reconcile
            # enqueue path acquires the lock and creates the pending row before the
            # send); refuse to claim so the caller suppresses rather than sending
            # without a durable ownership marker.
            return False
        owner = _normalize_lock_owner(lock_owner)
        res = await self.db.execute(
            text(
                """
                UPDATE messages SET delivery_status = 'SENDING', body = :reply
                 WHERE id = :pending_id
                   AND conversation_id = :cid
                   AND sender = 'BOT'
                   AND delivery_status = 'PENDING'
                   AND EXISTS (
                       SELECT 1 FROM conversations c
                        WHERE c.id = :cid
                          AND c.version = :version_at_start
                          AND c.bot_lock_owner = :owner
                          AND c.bot_locked_until IS NOT NULL
                          AND c.bot_locked_until > now()
                   )
                """
            ),
            {
                "pending_id": pending_message_id,
                "cid": conv.id,
                "version_at_start": version_at_start,
                "owner": owner,
                "reply": reply,
            },
        )
        if affected_rows(res) == 1 and outbox_channel is not None and outbox_payload is not None:
            from app.models.outbox import OutboxStatus
            from app.services.outbox_service import create_pending_outbox

            pending = await self.db.get(Message, pending_message_id)
            stamped = pending is not None and pending.runtime_revision_id is not None

            # REL-06: write the command already SENDING. It is claimed by this
            # very transaction (the message flip above is its claim), so a 60 s
            # dispatcher tick can no longer win a row whose inline send is still
            # running and record a false ERROR turn for a delivered message. The
            # inline sender resumes it through ``dispatch_message_outbox``; a
            # crash leaves SENDING, which the recovery sweep terminalizes
            # at-most-once rather than re-sending.
            await create_pending_outbox(
                self.db,
                message_id=pending_message_id,
                channel=outbox_channel,
                payload=outbox_payload,
                runtime_revision_id=pending.runtime_revision_id if stamped else None,
                authority_generation=pending.authority_generation if stamped else None,
                runtime_fingerprint=pending.runtime_fingerprint if stamped else None,
                origin_kind="BOT" if stamped else None,
                fence_scope="RUNTIME" if stamped else None,
                status=OutboxStatus.SENDING,
            )
        await self.db.commit()
        return affected_rows(res) == 1

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
        """Finalize a recovered command for any outbound sender without a new row."""
        from app.models.outbox import OutboxStatus, OutboundOutbox

        msg = await self.db.get(Message, message_id)
        outbox = await self.db.get(OutboundOutbox, outbox_id)
        if msg is None or msg.conversation_id != conv.id or outbox is None:
            raise RuntimeError("outbound message disappeared before dispatch finalization")
        delivery_status = (
            DeliveryStatus.SUPPRESSED
            if suppressed
            else _delivery_status_for_send_error(error_class, ok=delivered)
        )
        if delivery_status is None:
            delivery_status = DeliveryStatus.SENT if delivered else DeliveryStatus.FAILED
        msg.delivery_status = delivery_status
        msg.zalo_message_id = zalo_message_id
        msg.provider_message_id = zalo_message_id
        msg.external_error = None if delivered else external_error
        outbox.status = (
            OutboxStatus.SUPPRESSED.value
            if suppressed
            else OutboxStatus.SENT.value
            if delivered
            else OutboxStatus.SEND_UNKNOWN.value
            if delivery_status == DeliveryStatus.SEND_UNKNOWN
            else OutboxStatus.FAILED.value
        )
        outbox.zalo_message_id = zalo_message_id
        outbox.provider_message_id = zalo_message_id
        outbox.last_error = None if delivered else external_error
        outbox.updated_at = utcnow()
        if delivered:
            outbox.sent_at = utcnow()
            conv.last_outbound_at = utcnow()
        if msg.sender == MessageSender.BOT:
            if telemetry is not None:
                telemetry_timings = telemetry.to_stage_timings()
                if msg.bot_run_id is not None:
                    run = await self.db.get(BotRun, msg.bot_run_id)
                    if run is not None:
                        merged_timings = dict(run.stage_timings or {})
                        merged_timings.update(telemetry_timings)
                        run.stage_timings = merged_timings
                else:
                    run = BotRun(
                        conversation_id=conv.id,
                        started_at=msg.created_at or utcnow(),
                        ended_at=utcnow(),
                        version_at_start=int(conv.version),
                        outcome=BotRunOutcome.SENT if delivered else BotRunOutcome.ERROR,
                        stage_timings={
                            "execution_source": "outbox_recovery",
                            "lane": "outbox_recovery",
                            **telemetry_timings,
                        },
                        decision_trace={
                            "version": 1,
                            "events": [
                                {
                                    "seq": 1,
                                    "kind": "decision",
                                    "code": "recovery_reason",
                                    "summary_code": "outbox_recovery",
                                }
                            ],
                            "truncated": False,
                        },
                    )
                    self.db.add(run)
                    await self.db.flush()
                    msg.bot_run_id = run.id
            # A stale-outbox finalization can run on the recovery sweep LONG
            # after the message's own turn ended (it fires only once the outbox
            # row exceeds ``chat_turn_job_timeout`` without a receipt). By then a
            # NEWER turn may already hold this conversation's lock — and clearing
            # it unconditionally here steals that live lock, causing the in-flight
            # turn's ``claim_send`` to suppress (the "Đã chặn" / SUPPRESSED bug).
            # Only clear a lock that is NOT live: one with no owner or whose TTL
            # already expired. A still-live lock belongs to a concurrent turn and
            # is left for its own ``record_bot_outcome`` / the reconciler's TTL
            # sweep. Conditional SQL (evaluated server-side at commit) mirrors the
            # owner-guarded pattern in ``release_lock`` / ``record_bot_outcome``.
            clear_lock = await self.db.execute(
                update(Conversation)
                .where(
                    Conversation.id == conv.id,
                    or_(
                        Conversation.bot_lock_owner.is_(None),
                        Conversation.bot_locked_until.is_(None),
                        Conversation.bot_locked_until <= utcnow(),
                    ),
                )
                .values(
                    bot_locked_until=None,
                    bot_lock_owner=None,
                    bot_lock_heartbeat_at=None,
                )
                .execution_options(synchronize_session=False)
            )
            if affected_rows(clear_lock) == 1:
                conv.bot_locked_until = None
                conv.bot_lock_owner = None
                conv.bot_lock_heartbeat_at = None
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox.attempts
        if error_class == USER_UNREACHABLE_SEND_CLASS:
            await apply_user_unreachable_side_effects(self.db, conv, self.events)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg
