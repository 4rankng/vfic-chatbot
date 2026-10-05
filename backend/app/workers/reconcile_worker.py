"""RQ worker: reactive reconciliation sweep for lost bot turns.

The ``scheduler`` container periodically enqueues ``run_reconcile_tick`` onto
the ``maintenance`` queue.  ``worker-maintenance`` consumes it and scans for
conversations whose newest message is unanswered or stuck-PENDING, then
re-enqueues a fresh chat turn through the ``enqueue_recovery_chat_run`` path
(low-priority ``recovery`` queue, consumed after ``webhook_high``).

This is the primary reliability guarantee: regardless of *how* a turn was
lost (OOM kill, SyntaxError, deploy force-recreate, exception-to-failed-queue,
enqueue-fail-after-dedup), the sweeper detects and recovers within one sweep
cycle (~60s scan + 120s grace ≈ 3-4 min total recovery).

Loop-safety: a completed turn (sent OR suppressed) leaves ``BOT/SENT`` or
``BOT/SUPPRESSED`` as the newest message → excluded.  ``acquire_lock`` is
taken *before* touching any PENDING row → overlapping ticks cannot double-enqueue.

One exception is deliberate (``_MASKED_INBOUND_SQL``): a completed outcome whose
own outbound command quotes a DIFFERENT inbound than the newest candidate message
answered an older message, so the newest candidate message was dropped by the
ingress while that turn held the per-chat mutex and never got a turn.  Without it
that outcome row hides the conversation from this sweep forever — the durable net
behind ``chatbot_worker._handoff_to_newer_inbound``.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Redis keys for observability counters (read by /metrics in main.py).
_RECONCILE_REENQUEUED = "reconcile_re_enqueues_total"
_RECONCILE_STALE_PENDING = "reconcile_stale_pending_total"
_RECONCILE_UNANSWERED_INBOUND = "reconcile_unanswered_inbound_total"
_RECONCILE_SUPERSEDED_INBOUND = "reconcile_superseded_inbound_total"
_RECONCILE_FAILED_SEND = "reconcile_failed_send_total"
_RECONCILE_FAILED_SEND_EXHAUSTED = "reconcile_failed_send_exhausted_total"
_RECONCILE_TERMINAL_SEND_SKIPPED = "reconcile_terminal_send_skipped_total"
_RECONCILE_SKIPPED_LOCKED = "reconcile_skipped_locked_total"
_RECONCILE_ENQUEUE_FAILED = "reconcile_enqueue_failed_total"
_RECONCILE_UNKNOWN_SEND = "reconcile_unknown_send_outcome"
_RECONCILE_SEND_UNKNOWN_SKIPPED = "reconcile_send_unknown_skipped_total"
_RECONCILE_STALE_LOCK_BROKEN = "reconcile_stale_lock_broken"
_RECONCILE_UNANSWERED_GAUGE = "reconcile_unanswered_gauge"
_RECONCILE_PARTIAL_DELIVERY_SKIPPED = "reconcile_partial_delivery_skipped_total"
_RECONCILE_TICK_LOCK = "reconcile_tick_lock"  # SETNX non-reentrancy key

# Release the tick lock only when this tick still owns it. A tick whose 300 s TTL
# expired while the sweep ran (the batch is up to ``reconcile_batch_size``
# conversations, each with its own session) must not delete the SUCCESSOR tick's
# lock — a blind DELETE would admit a third concurrent sweep on top of the new
# owner. The same ownership CAS as ``core/singleflight.release``, made atomic in
# Lua because this worker holds the sync Redis client.
_RELEASE_TICK_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def _release_tick_lock(conn, owner_id: str) -> None:  # noqa: ANN001 (sync Redis client)
    """Delete ``_RECONCILE_TICK_LOCK`` iff this tick is still its owner."""
    conn.eval(_RELEASE_TICK_LOCK_LUA, 1, _RECONCILE_TICK_LOCK, owner_id)


def _delivered_a_provider_message(message) -> bool:  # noqa: ANN001 (Message ORM row)
    """Whether a FAILED BOT row already carries a provider message id.

    An answer longer than ``ZALO_VISIBLE_BUBBLE_CHARS`` is sent as N provider
    requests. The first accepted bubble stamps its id on the row while a later
    bubble can still fail, so a non-null id on a FAILED row means the answer was
    *partially* delivered: re-answering would duplicate the bubbles the candidate
    already saw. The candidate scan excludes these rows; this is the fresh
    re-check against state read after the scan.
    """
    return bool(
        getattr(message, "provider_message_id", None)
        or getattr(message, "zalo_message_id", None)
    )

# A conversation whose newest message is a FAILED BOT row is a candidate again
# on the very next tick — the failed row is what makes it a candidate — so the
# sweep used to re-answer it with a full LLM turn every ~2 minutes, forever.
# When the failure is not transient (unresolvable Page token, provider
# rejection) that is a self-sustaining load generator: production carried 300k
# re-enqueued recovery turns and 298k stale-lock breaks against 352 recorded
# runs, and every one of them competes with live candidate turns for the two
# chat workers. Wait this long between delivery-failure retries; lost-turn
# recovery (WORKER/PENDING/SENDING newest) keeps its fast ~60s cadence.
_FAILED_SEND_RETRY_BACKOFF_SECONDS = 900

# A backoff alone cannot stop a failure that is not transient: the retry writes
# the NEXT failed row, so the conversation becomes a candidate again forever,
# only slower. Production carried threads that re-answered the same inbound with
# the same undeliverable reply every ~16 minutes for hours — a candidate-visible
# spam loop, since the provider refusal is retried, not the candidate's patience.
# Two attempts is the cap: the original turn plus one recovery turn. After that
# the conversation waits for a recruiter (the console shows the failed bubbles).
_FAILED_SEND_MAX_ATTEMPTS = 2

# Provider errors that no retry can fix: the channel's credential is dead, so the
# next attempt fails exactly the same way. The live case: the Zalo OA refresh
# token was refused with ``-14014 Invalid refresh token`` (the app secret was
# re-issued), so every send on that OA came back "Access token has expired" and
# the sweep kept re-generating the same undeliverable reply. Retrying such a
# conversation burns a full LLM turn and adds another failed bubble to the
# candidate's thread; the operator has to re-authorize the channel instead.
# Matched case-insensitively against ``messages.external_error``.
_TERMINAL_SEND_ERROR_MARKERS = (
    "access token has expired",
    "invalid access token",
    "refresh token has expired",
    "invalid refresh token",
)


def _is_terminal_send_failure(message) -> bool:  # noqa: ANN001 (Message ORM row)
    """Whether the recorded send failure is a dead-credential error, not a blip."""
    text = str(getattr(message, "external_error", "") or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _TERMINAL_SEND_ERROR_MARKERS)


def _within_failed_send_backoff(newest, *, now: datetime) -> bool:
    """Whether *newest* is a BOT delivery failure younger than the retry backoff."""
    created_at = getattr(newest, "created_at", None)
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (now - created_at).total_seconds() < _FAILED_SEND_RETRY_BACKOFF_SECONDS


async def _failed_send_attempts(db, conversation_id, *, since: datetime) -> int:  # noqa: ANN001
    """How many BOT replies to this inbound the provider has already refused.

    Counted from the messages themselves rather than a marker: a marker would
    live in Redis (lost on flush) while the failed bubbles are exactly what the
    console shows the recruiter, so the cap and the visible state agree.
    """
    from sqlalchemy import func, select

    from app.models.conversation import DeliveryStatus, Message, MessageSender

    statement = (
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.sender == MessageSender.BOT,
            Message.delivery_status == DeliveryStatus.FAILED,
            Message.created_at >= since,
        )
    )
    return int((await db.scalar(statement)) or 0)


def enqueue_reconcile_tick_now() -> bool:
    """One-shot helper: enqueue a reconcile tick onto the ``maintenance`` queue.
    Useful for ops manual-trigger + tests. Must match the queue the scheduler
    registers the tick on, so a manual run lands on the maintenance worker
    instead of head-of-line-blocking proactive nudges."""
    from app.workers.utils import enqueue_job

    return enqueue_job("maintenance", run_reconcile_tick)


def run_reconcile_tick() -> None:
    """Scheduler tick (sync entrypoint). Scans for lost bot turns and re-enqueues."""
    from app.workers.async_runner import run_async

    run_async(_run_tick_async())


async def _run_tick_async() -> None:
    from app.core.redis import get_redis_sync

    conn = get_redis_sync()

    # ── Non-reentrancy guard: skip if a prior tick is still running ──
    # The stored value is this tick's own id, so the release below can prove
    # ownership before deleting (see ``_release_tick_lock``).
    tick_owner = uuid.uuid4().hex
    if not conn.set(_RECONCILE_TICK_LOCK, tick_owner, nx=True, ex=300):
        logger.debug("reconcile tick: skipped — prior tick still running")
        return

    try:
        await _sweep(conn)
    finally:
        _release_tick_lock(conn, tick_owner)


async def _sweep(conn) -> None:  # noqa: ANN001 (sync Redis client)
    """Core sweep: find candidates, re-enqueue where possible."""
    from app.core.config import get_settings
    from app.services.conversation import ConversationService
    from app.services.conversation.repository import (
        SUPERSEDED_OUTCOME_STATUSES,
        ConversationRepository,
    )
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

    from app.workers.chatbot_worker import enqueue_recovery_chat_run

    re_enqueued = 0
    stale_pending = 0
    unanswered_inbound = 0
    superseded_inbound = 0
    failed_send = 0
    skipped_locked = 0
    enqueue_failed = 0
    unknown_send_outcome = 0
    send_unknown_skipped = 0
    stale_locks_broken = 0
    failed_send_backoff = 0
    failed_send_exhausted = 0
    terminal_send_skipped = 0
    partial_delivery_skipped = 0

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
                    # A completed BOT outcome whose durable outbound command
                    # quotes a DIFFERENT inbound answered an older message: the
                    # newest candidate message arrived while that turn held the
                    # per-chat mutex, the ingress dropped it, and it never got a
                    # turn. The outcome row is what hid the conversation from this
                    # sweep. Re-verified against freshly read state — a turn
                    # enqueued since the scan may have answered the message since,
                    # and then the newest outcome quotes it and this is False.
                    # Only the statuses the sweep selects for this branch can
                    # match, so a stale placeholder or a delivery failure keeps
                    # its own recovery path below untouched.
                    superseded = (
                        newest.delivery_status.name in SUPERSEDED_OUTCOME_STATUSES
                        and await repo.latest_inbound_never_given_a_turn(
                            conv_fresh,
                            now=now,
                            grace_seconds=settings.reconcile_grace_seconds,
                            max_age_seconds=settings.reconcile_max_age_seconds,
                        )
                    )
                    if superseded:
                        reason = "superseded_inbound"
                    elif newest.delivery_status.name == "PENDING":
                        reason = "stale_pending"
                    elif newest.delivery_status.name == "FAILED":
                        if _delivered_a_provider_message(newest):
                            # REL-01: the row already carries a provider message
                            # id, so at least the first bubble of a chunked answer
                            # reached the candidate. Partially delivered is not a
                            # lost turn — re-answering would duplicate it. The
                            # scan excludes these rows; re-checked here because
                            # the id can be stamped between scan and this read.
                            partial_delivery_skipped += 1
                            await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                            continue
                        if _is_terminal_send_failure(newest):
                            # The channel credential itself is dead (expired OA
                            # access token, refused refresh token). A recovery
                            # turn cannot deliver anything; it only adds another
                            # failed bubble the candidate can see.
                            terminal_send_skipped += 1
                            await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                            continue
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

                if reason == "failed_send" and _within_failed_send_backoff(newest, now=now):
                    # Already tried to deliver a reply this recently; retrying
                    # every tick only burns worker capacity (see the constant).
                    await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                    failed_send_backoff += 1
                    continue

                if reason == "failed_send" and (
                    await _failed_send_attempts(
                        db, conv_fresh.id, since=msg.created_at if msg else now
                    )
                    >= _FAILED_SEND_MAX_ATTEMPTS
                ):
                    # Two replies have already been refused for this inbound. The
                    # provider is not going to accept a third, and each retry
                    # leaves another failed bubble in the thread. Stop: the
                    # conversation stays visible to a recruiter with its failed
                    # replies, and a candidate who writes again starts a fresh
                    # attempt counter (their new inbound is a newer ``since``).
                    await svc.state.release_lock(conv_fresh, lock_owner=lock_owner)
                    failed_send_exhausted += 1
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
                ok = enqueue_recovery_chat_run(
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
                elif reason == "superseded_inbound":
                    superseded_inbound += 1
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
    if superseded_inbound:
        pipe.incrby(_RECONCILE_SUPERSEDED_INBOUND, superseded_inbound)
    if failed_send:
        pipe.incrby(_RECONCILE_FAILED_SEND, failed_send)
    if failed_send_exhausted:
        pipe.incrby(_RECONCILE_FAILED_SEND_EXHAUSTED, failed_send_exhausted)
    if terminal_send_skipped:
        pipe.incrby(_RECONCILE_TERMINAL_SEND_SKIPPED, terminal_send_skipped)
    if skipped_locked:
        pipe.incrby(_RECONCILE_SKIPPED_LOCKED, skipped_locked)
    if enqueue_failed:
        pipe.incrby(_RECONCILE_ENQUEUE_FAILED, enqueue_failed)
    if unknown_send_outcome:
        pipe.incrby(_RECONCILE_UNKNOWN_SEND, unknown_send_outcome)
    if send_unknown_skipped:
        pipe.incrby(_RECONCILE_SEND_UNKNOWN_SKIPPED, send_unknown_skipped)
    if partial_delivery_skipped:
        pipe.incrby(_RECONCILE_PARTIAL_DELIVERY_SKIPPED, partial_delivery_skipped)
    if stale_locks_broken:
        pipe.incrby(_RECONCILE_STALE_LOCK_BROKEN, stale_locks_broken)
    pipe.execute()
    logger.info(
        "reconcile tick complete: %d candidates scanned, %d re-enqueued, %d "
        "delivery-failure retries deferred, %d delivery-failure retries given up, "
        "%d dead-credential sends skipped, %d send_unknown skipped, "
        "%d partial deliveries skipped",
        len(candidates),
        re_enqueued,
        failed_send_backoff,
        failed_send_exhausted,
        terminal_send_skipped,
        send_unknown_skipped,
        partial_delivery_skipped,
    )
    if terminal_send_skipped:
        logger.warning(
            "reconcile: %d conversations have an undeliverable reply because the "
            "channel credential is dead (expired access token / refused refresh "
            "token); re-authorize the channel — no retry can deliver these",
            terminal_send_skipped,
        )
