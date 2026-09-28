#!/usr/bin/env python3
"""Resumable, observable backfill of Messenger candidate extraction.

Every Messenger turn that already accumulated a conversation failed to write
its lead: the candidate pipeline keyed the lead on a chat id while Messenger
conversations have ``zalo_chat_id IS NULL``, so the write died on
``leads_zalo_id_fkey`` and the worker swallowed it. The write path is now
contact-keyed, and this script replays the history that was lost.

Each (candidate message, next bot reply) pair is re-enqueued as the same
``run_persist_candidate_job`` live traffic uses, in chronological order, so the
COALESCE merge sees the earliest self-reported value for every field. The
merge is idempotent: re-running adds no duplicate note lines.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation_messaging.domain.statuses import MessageSender
from app.core.db import get_engine, get_session_factory
from app.models.contact import ContactChannelIdentity
from app.models.conversation import Conversation, Message

logger = logging.getLogger(__name__)

# Distinct from the OA profile sweep (0x564649434F415052) so the two backfills
# can never hold each other's lock.
_BACKFILL_ADVISORY_LOCK_KEY = 0x564649434D534547

_MESSENGER_PROVIDER = "facebook_messenger"


@dataclass(frozen=True)
class EligibleConversation:
    conversation_id: uuid.UUID
    contact_id: uuid.UUID
    psid: str


@dataclass(frozen=True)
class TurnPair:
    user_text: str
    bot_output: str


@dataclass
class _RunReport:
    """Mutable counters for one backfill run.

    Holding the counters as real ints keeps every increment a plain ``+=``; the
    earlier stringly-typed dict forced each one to re-parse its own value.
    """

    run_id: str
    dry_run: bool = False
    lock_acquired: bool = False
    eligible_at_start: int = 0
    processed: int = 0
    turns: int = 0
    enqueued: int = 0
    enqueue_failed: int = 0
    skipped_no_bot: int = 0
    skipped_blank: int = 0
    limit_reached: bool = False

    def as_payload(self) -> dict[str, int | bool | str]:
        """Flat fields of the ``final`` event; ``_emit`` supplies ``run_id`` itself."""
        return {
            "dry_run": self.dry_run,
            "lock_acquired": self.lock_acquired,
            "eligible_at_start": self.eligible_at_start,
            "processed": self.processed,
            "turns": self.turns,
            "enqueued": self.enqueued,
            "enqueue_failed": self.enqueue_failed,
            "skipped_no_bot": self.skipped_no_bot,
            "skipped_blank": self.skipped_blank,
            "limit_reached": self.limit_reached,
        }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the plan, enqueue nothing")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument(
        "--limit", type=int, default=0, help="0 processes every eligible conversation"
    )
    parser.add_argument(
        "--conversation-id",
        action="append",
        default=[],
        dest="conversation_ids",
        help="Restrict the run to this conversation id (repeatable).",
    )
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be zero or greater")
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    return args


def _eligible_statement():
    """Messenger conversations with a NULL zalo_chat_id, in id order.

    That NULL is exactly why their lead write failed, so this is the same
    population as the leads the contact-keyed write now merges into.
    """
    return (
        select(Conversation.id, Conversation.contact_id, ContactChannelIdentity.external_id)
        .join(
            ContactChannelIdentity,
            Conversation.channel_identity_id == ContactChannelIdentity.id,
        )
        .where(
            ContactChannelIdentity.provider == _MESSENGER_PROVIDER,
            Conversation.zalo_chat_id.is_(None),
        )
        .order_by(Conversation.id)
    )


async def _eligible_page(
    session: AsyncSession,
    *,
    after: uuid.UUID | None,
    batch_size: int,
    only: list[str] | None = None,
) -> list[EligibleConversation]:
    statement = _eligible_statement().limit(batch_size)
    if after is not None:
        statement = statement.where(Conversation.id > after)
    if only:
        statement = statement.where(Conversation.id.in_([uuid.UUID(value) for value in only]))
    rows = (await session.execute(statement)).all()
    return [EligibleConversation(*row) for row in rows]


async def _eligible_count(session: AsyncSession) -> int:
    statement = select(func.count()).select_from(_eligible_statement().subquery())
    # ``func.count()`` is an integer column, so the scalar needs no cast.
    total: int = await session.scalar(statement) or 0
    return total


def _turn_pairs(messages: list[tuple[MessageSender, str]]) -> tuple[list[TurnPair], int, int]:
    """Pair each candidate message with the next bot reply.

    A candidate message with no following bot reply has no turn to extract
    from and is skipped; so is a blank body. When two candidate messages are
    adjacent the earlier one has no bot reply after it either, so it is
    skipped and the later one keeps the slot.
    """
    pairs: list[TurnPair] = []
    skipped_no_bot = 0
    skipped_blank = 0
    pending: str | None = None
    for sender, body in messages:
        if sender == MessageSender.BOT:
            if pending is not None:
                pairs.append(TurnPair(user_text=pending, bot_output=body))
                pending = None
            continue
        if sender != MessageSender.WORKER:
            continue
        if pending is not None:
            skipped_no_bot += 1
        pending = body.strip() or None
        if pending is None:
            skipped_blank += 1
    if pending is not None:
        skipped_no_bot += 1
    return pairs, skipped_no_bot, skipped_blank


async def _conversation_turns(
    session: AsyncSession, conversation_id: uuid.UUID
) -> tuple[list[TurnPair], int, int]:
    statement = (
        select(Message.sender, Message.body)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    )
    rows = (await session.execute(statement)).all()
    return _turn_pairs([(sender, body) for sender, body in rows])


@asynccontextmanager
async def _exclusive_backfill() -> AsyncIterator[bool]:
    """Hold a crash-safe PostgreSQL session advisory lock for the whole run."""
    async with get_engine().connect() as connection:
        acquired = bool(
            await connection.scalar(select(func.pg_try_advisory_lock(_BACKFILL_ADVISORY_LOCK_KEY)))
        )
        try:
            yield acquired
        finally:
            if acquired:
                await connection.execute(
                    select(func.pg_advisory_unlock(_BACKFILL_ADVISORY_LOCK_KEY))
                )


def _emit(event: str, run_id: str, **values: object) -> None:
    print(json.dumps({"event": event, "run_id": run_id, **values}, sort_keys=True), flush=True)


def _enqueue(pair: TurnPair, conversation: EligibleConversation) -> bool:
    """Re-run one historical turn through the live candidate persistence job."""
    from app.workers.persistence_worker import run_persist_candidate_job
    from app.workers.utils import enqueue_job

    return bool(
        enqueue_job(
            "persistence_low",
            run_persist_candidate_job,
            {
                # The PSID is what the graph passes as recipient_id, so the lead
                # lookup and the memory dedup namespace match live traffic.
                "chat_id": conversation.psid,
                "user_text": pair.user_text,
                "bot_output": pair.bot_output,
                "conversation_id": str(conversation.conversation_id),
                "contact_id": str(conversation.contact_id),
                # History is not "current" any more; None skips only the
                # version half of the staleness guard.
                "conversation_version": None,
            },
        )
    )


async def _run(args: argparse.Namespace) -> _RunReport:
    only = list(args.conversation_ids) or None
    async with get_session_factory()() as session:
        if only:
            eligible_at_start = len(
                await _eligible_page(session, after=None, batch_size=len(only), only=only)
            )
        else:
            eligible_at_start = await _eligible_count(session)
    report = _RunReport(
        run_id=uuid.uuid4().hex,
        dry_run=bool(args.dry_run),
        eligible_at_start=eligible_at_start,
    )
    _emit("start", report.run_id, dry_run=report.dry_run, eligible=eligible_at_start)

    if args.dry_run:
        cursor: uuid.UUID | None = None
        shown = 0
        while True:
            async with get_session_factory()() as session:
                page = await _eligible_page(
                    session, after=cursor, batch_size=args.batch_size, only=only
                )
            if not page:
                break
            for conversation in page:
                async with get_session_factory()() as session:
                    pairs, no_bot, blank = await _conversation_turns(
                        session, conversation.conversation_id
                    )
                report.processed += 1
                report.turns += len(pairs)
                report.skipped_no_bot += no_bot
                report.skipped_blank += blank
                for pair in pairs:
                    if shown < 10:
                        shown += 1
                        _emit(
                            "turn",
                            report.run_id,
                            conversation_id=str(conversation.conversation_id),
                            psid=conversation.psid,
                            user_text=pair.user_text[:200],
                            bot_output=pair.bot_output[:200],
                        )
            cursor = page[-1].conversation_id
        _emit("final", report.run_id, **report.as_payload())
        return report

    async with _exclusive_backfill() as acquired:
        report.lock_acquired = acquired
        if not acquired:
            _emit("locked", report.run_id)
            _emit("final", report.run_id, **report.as_payload())
            return report

        cursor = None
        batch_number = 0
        while args.limit == 0 or report.processed < args.limit:
            page_size = args.batch_size
            if args.limit:
                page_size = min(page_size, args.limit - report.processed)
            async with get_session_factory()() as session:
                page = await _eligible_page(session, after=cursor, batch_size=page_size, only=only)
            if not page:
                break
            batch_number += 1
            for conversation in page:
                async with get_session_factory()() as session:
                    pairs, no_bot, blank = await _conversation_turns(
                        session, conversation.conversation_id
                    )
                report.processed += 1
                report.turns += len(pairs)
                report.skipped_no_bot += no_bot
                report.skipped_blank += blank
                # Oldest turn first, so the replay matches the order the
                # candidate actually spoke in: each non-blank field replaces the
                # previous one (a corrected number lands) while notes accumulate
                # line by line without duplicating what is already stored.
                for pair in pairs:
                    if _enqueue(pair, conversation):
                        report.enqueued += 1
                    else:
                        report.enqueue_failed += 1
            cursor = page[-1].conversation_id
            _emit(
                "batch",
                report.run_id,
                batch=batch_number,
                processed=report.processed,
                turns=report.turns,
                enqueued=report.enqueued,
                enqueue_failed=report.enqueue_failed,
            )

    report.limit_reached = bool(args.limit and report.processed >= args.limit)
    _emit("final", report.run_id, **report.as_payload())
    return report


def _exit_code(args: argparse.Namespace, report: _RunReport) -> int:
    if args.dry_run:
        return 0
    if not report.lock_acquired:
        return 3
    if report.enqueue_failed > 0:
        return 2
    return 0


async def _main(args: argparse.Namespace) -> int:
    try:
        return _exit_code(args, await _run(args))
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
