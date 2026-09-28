#!/usr/bin/env python3
"""Post-flip turn-pipeline gate: is the bot actually ANSWERING?

``smoke_turn`` proves the turn *code* works on the new color. It does not prove
a worker is consuming ``webhook_high``: the 2026-09-26 incident had healthy
containers, a passing smoke gate, HTTP 200 webhooks — and recruiters getting no
reply for minutes, because ``worker-chatbot`` had been recreated and was still
preloading (83 s) while inbound turns sat in the queue.

This gate closes that hole. It inspects the live pipeline instead of the
process, and fails when work is *stalled*:

  * an inbound worker message newer than ``--window`` with no BOT reply after it
    (a conversation waiting for an answer), or
  * a ``PENDING`` outbound row older than ``--stale-after`` (dispatch not
    draining), or
  * a registered worker count below the declared queue consumers.
    ``rq:queue:webhook_high`` must have at least one live worker; with zero
    registered consumers, accepted webhooks can only queue.

Transient conditions are intentional non-failures: a turn started seconds ago is
not a stall. Both thresholds are age-based, so a healthy retry after a short
deploy gap still passes once the queue drains.

Usage (inside the active color / any app container):

    python -m scripts.turn_pipeline_check
    python -m scripts.turn_pipeline_check --window 600 --stale-after 300

Self-test — proves the gate's failure path actually fails (the consumer
assertion, which is the one that would have caught 2026-09-26):

    python -m scripts.turn_pipeline_check --min-consumers 999   # MUST exit 1

Exit 0 only when the pipeline is draining. Any stall exits 1 with a report that
names the queue depth, the stalled conversation ids, and the oldest pending row.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

import redis as redis_lib
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.conversation_messaging.domain.statuses import ConversationMode, MessageSender
from app.core.redis import sync_value
from app.core.config import get_settings
from app.models.conversation import BotRun, Conversation, Message
from app.models.outbox import OutboundOutbox, OutboxStatus

# Queues a turn passes through: inbound turn execution, then delayed re-drive,
# then outbound dispatch.
CONSUMED_QUEUES = ("webhook_high", "recovery", "maintenance")
# Queue whose consumers determine whether an accepted webhook can ever run.
CRITICAL_QUEUE = "webhook_high"

DEFAULT_WINDOW_SECONDS = 300
DEFAULT_STALE_AFTER_SECONDS = 120


def _fail(message: str) -> None:
    print(f"PIPELINE FAIL: {message}", file=sys.stderr)


def _redis_connection(settings) -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url)


def _queue_depths(client: redis_lib.Redis) -> dict[str, int]:
    depths: dict[str, int] = {}
    for queue in CONSUMED_QUEUES:
        try:
            depths[queue] = int(sync_value(client.llen(f"rq:queue:{queue}")))
        except redis_lib.RedisError:
            depths[queue] = -1
    return depths


def _live_worker_queues(client: redis_lib.Redis) -> dict[str, int]:
    """Count live RQ registrations per queue from the worker registry.

    RQ refreshes a worker's registration key while its work loop runs, so an
    expired key means a dead loop even when the container reports healthy.
    """
    from rq import Worker

    counts: dict[str, int] = {}
    try:
        workers = Worker.all(connection=client)
    except Exception:  # noqa: BLE001 - registry shape drift must not mask a stall
        return counts
    for worker in workers:
        for queue in getattr(worker, "queues", []) or []:
            name = getattr(queue, "name", str(queue))
            counts[name] = counts.get(name, 0) + 1
    return counts


async def _stalled_conversations(db, window_seconds: int) -> list[tuple[str, str]]:
    """Bot-eligible conversations whose newest inbound has no BOT reply after it.

    Filtered to avoid the legitimate non-reply cases, which are not stalls:

      * conversations the bot is not supposed to answer (HUMAN / CLOSED /
        SEMI_AUTO-with-active-human starve the bot by design), so only ``BOT``
        mode is considered;
      * turns that are still in flight — a conversation with an open
        ``bot_runs`` row started after its newest inbound is being worked on.
    """
    since = datetime.now(UTC) - timedelta(seconds=window_seconds)
    inbound = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.max(Message.created_at).label("last_inbound"),
        )
        .where(
            Message.sender == MessageSender.WORKER.value,
            Message.created_at > since,
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    reply = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.max(Message.created_at).label("last_bot"),
        )
        .where(Message.sender == MessageSender.BOT.value)
        .group_by(Message.conversation_id)
        .subquery()
    )
    running = (
        select(
            BotRun.conversation_id.label("conversation_id"),
            func.max(BotRun.started_at).label("last_started"),
        )
        .where(BotRun.ended_at.is_(None))
        .group_by(BotRun.conversation_id)
        .subquery()
    )
    rows = await db.execute(
        select(inbound.c.conversation_id, inbound.c.last_inbound, reply.c.last_bot)
        .join(
            Conversation,
            Conversation.id == inbound.c.conversation_id,
        )
        .join(reply, reply.c.conversation_id == inbound.c.conversation_id, isouter=True)
        .join(
            running,
            running.c.conversation_id == inbound.c.conversation_id,
            isouter=True,
        )
        .where(
            Conversation.mode == ConversationMode.BOT.value,
            (reply.c.last_bot.is_(None)) | (reply.c.last_bot < inbound.c.last_inbound),
            (running.c.last_started.is_(None))
            | (running.c.last_started < inbound.c.last_inbound),
        )
    )
    return [
        (str(conv_id), last_inbound.isoformat())
        for conv_id, last_inbound, _last_bot in rows.all()
    ]


async def _stale_pending(db, stale_after_seconds: int) -> list[tuple[int, str]]:
    """PENDING outbound rows older than the dispatch tolerance."""
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    rows = await db.execute(
        select(OutboundOutbox.id, OutboundOutbox.created_at)
        .where(
            OutboundOutbox.status == OutboxStatus.PENDING.value,
            OutboundOutbox.created_at < cutoff,
        )
        .order_by(OutboundOutbox.created_at)
    )
    return [(row[0], row[1].isoformat()) for row in rows.all()]


async def _run_check(
    *,
    window_seconds: int,
    stale_after_seconds: int,
    min_consumers: int = 1,
) -> int:
    settings = get_settings()
    client = _redis_connection(settings)
    depths = _queue_depths(client)
    consumers = _live_worker_queues(client)

    print(f"queue depths      : {depths}")
    print(f"live consumers    : {consumers}")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            stalled = await _stalled_conversations(db, window_seconds)
            stale = await _stale_pending(db, stale_after_seconds)
    finally:
        await engine.dispose()

    print(f"awaiting reply    : {len(stalled)} in the last {window_seconds}s")
    print(
        f"stale PENDING     : {len(stale)} older than {stale_after_seconds}s"
    )

    failed = False
    if consumers.get(CRITICAL_QUEUE, 0) < min_consumers:
        _fail(
            f"{consumers.get(CRITICAL_QUEUE, 0)} live worker(s) consuming "
            f"{CRITICAL_QUEUE!r}, need at least {min_consumers}; accepted webhooks "
            f"cannot run (registered consumers: {consumers or 'none'})"
        )
        failed = True
    if stalled:
        for conv_id, last_inbound in stalled:
            print(f"    no reply: conversation={conv_id} inbound={last_inbound}")
        _fail(
            f"{len(stalled)} conversation(s) with no BOT reply after the newest "
            f"inbound in the last {window_seconds}s"
        )
        failed = True
    if stale:
        for outbox_id, created_at in stale:
            print(f"    not dispatched: outbox_id={outbox_id} created={created_at}")
        _fail(
            f"{len(stale)} outbound row(s) PENDING for more than {stale_after_seconds}s"
        )
        failed = True

    if failed:
        return 1
    print("PIPELINE OK: consumers live, no conversation awaiting a reply, outbox drained")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW_SECONDS,
        help="seconds to look back for answerable inbound messages",
    )
    parser.add_argument(
        "--stale-after",
        type=int,
        default=DEFAULT_STALE_AFTER_SECONDS,
        help="seconds a PENDING outbound row may wait before it counts as stalled",
    )
    parser.add_argument(
        "--min-consumers",
        type=int,
        default=1,
        help=(
            "required live workers on the critical queue. Self-test the gate's "
            "failure path with `--min-consumers 999` (MUST exit 1)"
        ),
    )
    args = parser.parse_args()
    return asyncio.run(
        _run_check(
            window_seconds=args.window,
            stale_after_seconds=args.stale_after,
            min_consumers=args.min_consumers,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
