"""RQ worker: reactive reconciliation sweep for lost bot turns.

The ``scheduler`` container periodically enqueues ``run_reconcile_tick`` onto
the ``followup`` queue.  ``worker-followup`` consumes it and scans for
conversations whose newest message is unanswered or stuck-PENDING, then
re-enqueues a fresh chat turn through the existing ``enqueue_chat_run`` path.

This is the primary reliability guarantee: regardless of *how* a turn was
lost (OOM kill, SyntaxError, deploy force-recreate, exception-to-failed-queue,
enqueue-fail-after-dedup), the sweeper detects and recovers within one sweep
cycle (~60s scan + 120s grace ≈ 3-4 min total recovery).

Loop-safety: a completed turn (sent OR suppressed) leaves ``BOT/SENT`` or
``BOT/SUPPRESSED`` as the newest message → excluded.  ``acquire_lock`` is
taken *before* touching any PENDING row → overlapping ticks cannot double-enqueue.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Redis keys for observability counters (read by /metrics in main.py).
_RECONCILE_REENQUEUED = "reconcile_re_enqueues_total"
_RECONCILE_STALE_PENDING = "reconcile_stale_pending_total"
_RECONCILE_UNANSWERED_INBOUND = "reconcile_unanswered_inbound_total"
_RECONCILE_FAILED_SEND = "reconcile_failed_send_total"
_RECONCILE_SKIPPED_LOCKED = "reconcile_skipped_locked_total"
_RECONCILE_ENQUEUE_FAILED = "reconcile_enqueue_failed_total"
_RECONCILE_UNKNOWN_SEND = "reconcile_unknown_send_outcome"
_RECONCILE_SEND_UNKNOWN_SKIPPED = "reconcile_send_unknown_skipped_total"
_RECONCILE_STALE_LOCK_BROKEN = "reconcile_stale_lock_broken"
_RECONCILE_UNANSWERED_GAUGE = "reconcile_unanswered_gauge"
_RECONCILE_TICK_LOCK = "reconcile_tick_lock"  # SETNX non-reentrancy key


def enqueue_reconcile_tick_now() -> bool:
    """One-shot helper: enqueue a reconcile tick onto the ``followup`` queue.
    Useful for ops manual-trigger + tests."""
    from app.workers.utils import enqueue_job

    return enqueue_job("followup", run_reconcile_tick)


def run_reconcile_tick() -> None:
    """Scheduler tick (sync entrypoint). Scans for lost bot turns and re-enqueues."""
    from app.workers.async_runner import run_async

    run_async(_run_tick_async())


async def _run_tick_async() -> None:
    from app.core.redis import get_redis_sync

    conn = get_redis_sync()

    # ── Non-reentrancy guard: skip if a prior tick is still running ──
    if not conn.set(_RECONCILE_TICK_LOCK, "1", nx=True, ex=300):
        logger.debug("reconcile tick: skipped — prior tick still running")
        return

    try:
        await _sweep(conn)
    finally:
        conn.delete(_RECONCILE_TICK_LOCK)


async def _sweep(conn) -> None:  # noqa: ANN001 (sync Redis client)
    """Core sweep: find candidates, re-enqueue where possible."""
    from app.core.config import get_settings
    from app.services.conversation import ConversationService
    from app.services.conversation.repository import ConversationRepository
    from app.workers._db import worker_session

    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with worker_session() as db:
        repo = ConversationRepository(db)
        candidates = await repo.find_reconcile_candidates(
            now=now,
            grace_seconds=settings.reconcile_grace_seconds,
            max_age_seconds=settings.reconcile_max_age_seconds,
            stale_lock_seconds=settings.chat_turn_job_timeout,
            limit=settings.reconcile_batch_size,
        )

    if not candidates:
        logger.debug("reconcile tick: no candidates")
        conn.set(_RECONCILE_UNANSWERED_GAUGE, "0")
        return

    from app.workers.chatbot_worker import enqueue_chat_run

    re_enqueued = 0
    stale_pending = 0
    unanswered_inbound = 0
    failed_send = 0
    skipped_locked = 0
    enqueue_failed = 0
    unknown_send_outcome = 0
    send_unknown_skipped = 0
    stale_locks_broken = 0

    for conv in candidates:
        async with worker_session() as db:
            # Fresh read of mode/version for Python-level guards.
            svc = ConversationService(db)
            conv_fresh = await svc.get(conv.id)
            if conv_fresh is None:
                continue

            # ── Guard: re-check run_start_guard (SEMI_AUTO inactivity, etc.) ──
            if not svc.state.run_start_guard(conv_fresh):
                continue

            # ── Guard: acquire per-chat lock (atomic; None = already in-flight) ──
            lock_owner = await svc.state.acquire_lock(conv_fresh.id)
            if lock_owner is None:
                # Lock held. If the owner's heartbeat is stale (older than the RQ job
                # timeout) the worker is presumed dead — break the stale lock and
                # re-acquire instead of stalling the chat for the full bot_lock_ttl.
                if await svc.state.break_stale_lock(
                    conv_fresh.id, stale_after_seconds=settings.chat_turn_job_timeout
                ):
                    stale_locks_broken += 1
                    lock_owner = await svc.state.acquire_lock(conv_fresh.id)
                if lock_owner is None:
                    skipped_locked += 1
                    continue

            try:
                # Refresh version AFTER acquiring lock to avoid stale optimistic-lock.
                await db.refresh(conv_fresh)

                # Mop up any stale SENDING rows for this conversation (newest or
                # buried) — a worker crash after the pre-send claim left them. A
                # conv only becomes a candidate once its newest message is older
                # than reconcile_grace_seconds, so any SENDING row here is past the
                # RQ job timeout and definitively stale. At-most-once: preserve the
                # ambiguous result and do NOT re-enqueue (would duplicate). Resolving
                # BEFORE reading newest means a formerly-SENDING newest becomes SEND_UNKNOWN
                # and naturally falls through to the release-and-continue path below.
                resolved = await svc.state.resolve_unconfirmed_sending(conv_fresh.id)
                if resolved:
                    unknown_send_outcome += resolved
                    logger.warning(
                        "reconcile: resolved %d unconfirmed SENDING row(s) as unknown "
                        "(at-most-once) conversation=%s",
                        resolved,
                        conv_fresh.zalo_chat_id,
                    )

                # Determine reason from the actual newest message.
                repo = ConversationRepository(db)
                newest = await repo.latest_message(conv_fresh)
                if newest is None:
                    await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                    continue

                # Get the inbound text to reply to.
                if newest.sender.name == "WORKER":
                    user_text = newest.body
                    reply_to_message_id = newest.zalo_message_id or ""
                    reason = "unanswered_inbound"
                else:
                    # Fallback: load the latest WORKER message body directly.
                    from app.models.conversation import Message, MessageSender
                    from sqlalchemy import desc, select

                    stmt = (
                        select(Message)
                        .where(
                            Message.conversation_id == conv_fresh.id,
                            Message.sender == MessageSender.WORKER,
                        )
                        .order_by(desc(Message.created_at), desc(Message.id))
                        .limit(1)
                    )
                    msg = (await db.scalars(stmt)).first()
                    user_text = msg.body if msg else ""
                    reply_to_message_id = msg.zalo_message_id if msg else ""
                    if newest.delivery_status.name == "PENDING":
                        reason = "stale_pending"
                    elif newest.delivery_status.name == "FAILED":
                        reason = "failed_send"
                    elif newest.delivery_status.name == "SEND_UNKNOWN":
                        # Ambiguous send (transport timeout after Zalo may have
                        # accepted the message). NON-retriable — re-enqueuing
                        # risks a duplicate reply. Release the lock and surface
                        # for manual review on the console.
                        send_unknown_skipped += 1
                        await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                        continue
                    else:
                        await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                        continue

                if not user_text:
                    # No inbound text to reply to — release and skip.
                    await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                    continue

                # ── Enqueue recovery turn ──
                # Stamp received_at_epoch so the recovered turn gets a FRESH ~10s
                # SLA budget from recovery time (not the original inbound time,
                # which would already be exhausted). Without it BotRunState's
                # deadline defaults to 0.0 → unbounded agent budget on recoveries.
                ok = enqueue_chat_run(
                    {
                        "conversation_id": str(conv_fresh.id),
                        "version_at_start": conv_fresh.version,
                        "user_text": user_text,
                        "user_name": "",
                        "reply_to_message_id": reply_to_message_id,
                        "lock_owner": str(lock_owner),
                        "execution_source": "recovery",
                        "received_at": datetime.now(timezone.utc).isoformat(),
                        "received_at_epoch": time.time(),
                    }
                )

                if not ok:
                    # Backpressure / Redis down — release lock, leave for next sweep.
                    await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                    enqueue_failed += 1
                    continue

                # ── Success: now safe to mark orphaned BOT/PENDING as FAILED ──
                if reason == "stale_pending":
                    await svc.state.mark_stale_pending_failed(conv_fresh.id)

                re_enqueued += 1
                if reason == "stale_pending":
                    stale_pending += 1
                elif reason == "failed_send":
                    failed_send += 1
                else:
                    unanswered_inbound += 1
                logger.info(
                    "reconcile: enqueued recovery turn conversation=%s reason=%s",
                    conv_fresh.zalo_chat_id,
                    reason,
                )

            except Exception:
                # Release lock on any exception so the conversation isn't stuck
                # until TTL expires.
                logger.exception(
                    "reconcile: error processing conversation=%s, releasing lock",
                    conv_fresh.zalo_chat_id,
                )
                try:
                    await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                except Exception:
                    logger.exception("reconcile: failed to release lock")
                continue

    # Flush counters: cumulative totals via INCR, gauge via SET.
    pipe = conn.pipeline()
    pipe.set(_RECONCILE_UNANSWERED_GAUGE, str(len(candidates)))
    if re_enqueued:
        pipe.incrby(_RECONCILE_REENQUEUED, re_enqueued)
    if stale_pending:
        pipe.incrby(_RECONCILE_STALE_PENDING, stale_pending)
    if unanswered_inbound:
        pipe.incrby(_RECONCILE_UNANSWERED_INBOUND, unanswered_inbound)
    if failed_send:
        pipe.incrby(_RECONCILE_FAILED_SEND, failed_send)
    if skipped_locked:
        pipe.incrby(_RECONCILE_SKIPPED_LOCKED, skipped_locked)
    if enqueue_failed:
        pipe.incrby(_RECONCILE_ENQUEUE_FAILED, enqueue_failed)
    if unknown_send_outcome:
        pipe.incrby(_RECONCILE_UNKNOWN_SEND, unknown_send_outcome)
    if send_unknown_skipped:
        pipe.incrby(_RECONCILE_SEND_UNKNOWN_SKIPPED, send_unknown_skipped)
    if stale_locks_broken:
        pipe.incrby(_RECONCILE_STALE_LOCK_BROKEN, stale_locks_broken)
    pipe.execute()
    logger.info(
        "reconcile tick complete: %d candidates scanned, %d re-enqueued, %d send_unknown skipped",
        len(candidates),
        re_enqueued,
        send_unknown_skipped,
    )
