#!/usr/bin/env python3
"""Fill candidate details for Messenger leads that are still blank.

``backfill_messenger_candidates`` replays every historical turn through the
persistence queue — correct, but it walks the whole population (including
conversations whose lead is already filled) at the worker's single-job
concurrency, one LLM round trip at a time. This script does the targeted half:
it scans for the leads that are still missing candidate details, reads each
one's conversation, and runs the SAME persistence path live traffic uses, with
several conversations in flight.

Why the details are missing at all: the Messenger User Profile API cannot
supply a name for this app. The Page token lacks ``pages_read_engagement``, so
every PSID lookup is refused with code 100 / subcode 33, the provider label on
``contacts.display_name`` is never filled, and the profile-name capture in the
graph turn has nothing to write. Until Meta grants that access, the only source
of candidate detail is what the candidate actually said — which is what this
replays.

Concurrency is bounded by the deployment-wide Redis semaphores
(``llm_concurrency_limit`` / ``embed_concurrency_limit``), which exist exactly
to throttle provider calls across processes. Each conversation keeps its turns
in chronological order (the merge replaces a field with the latest non-blank
value, so replaying out of order would let an older answer win), while separate
conversations are processed independently.

The merge is idempotent and blank-only: re-running writes nothing new, and a
lead a recruiter has already filled is never overwritten.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_engine, get_session_factory
from app.models.conversation import Conversation
from app.models.lead import Lead
from scripts.backfill_messenger_candidates import (
    EligibleConversation,
    _conversation_turns,
    _eligible_statement,
    _exclusive_backfill,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONCURRENCY = 6

_CANDIDATE_DETAIL_COLUMNS = ("name", "phone")


@dataclass
class _RunReport:
    """Mutable counters for one run."""

    run_id: str
    dry_run: bool = False
    eligible_at_start: int = 0
    processed: int = 0
    turns: int = 0
    pairs_applied: int = 0
    pair_failures: int = 0
    skipped_no_bot: int = 0
    skipped_blank: int = 0
    limit_reached: bool = False
    lock_acquired: bool = False

    def as_payload(self) -> dict:
        return {
            "processed": self.processed,
            "turns": self.turns,
            "pairs_applied": self.pairs_applied,
            "pair_failures": self.pair_failures,
            "skipped_no_bot": self.skipped_no_bot,
            "skipped_blank": self.skipped_blank,
            "eligible_at_start": self.eligible_at_start,
            "limit_reached": self.limit_reached,
            "lock_acquired": self.lock_acquired,
        }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the plan, extract nothing")
    parser.add_argument(
        "--limit", type=int, default=0, help="process at most N conversations (0 = all)"
    )
    parser.add_argument("--batch-size", type=int, default=50, help="conversations per page")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help="conversations processed in parallel",
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
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    return args


def _blank_lead_statement():
    """Eligible Messenger conversations whose lead still carries no details.

    "No details" is every column a candidate would have to have stated for the
    panel to be useful, all blank. A lead with only a name is already useful and
    is left alone, so a re-run after a partial backfill narrows on its own.

    ``EXISTS`` rather than a join to ``leads``: one contact can hold more than
    one lead row, and a join would return the same conversation once per blank
    row — re-extracting its whole history for no gain. Correlating on the
    contact asks the question once, and answers it the same way (a conversation
    is eligible when any of its contact's leads is still blank).
    """
    return _eligible_statement().where(
        select(1)
        .where(
            Lead.contact_id == Conversation.contact_id,
            *(
                func.coalesce(func.btrim(getattr(Lead, column)), "") == ""
                for column in _CANDIDATE_DETAIL_COLUMNS
            ),
        )
        .correlate(Conversation)
        .exists()
    )


async def _blank_lead_page(
    session: AsyncSession,
    *,
    after: uuid.UUID | None,
    batch_size: int,
    only: list[str] | None = None,
) -> list[EligibleConversation]:
    statement = _blank_lead_statement().limit(batch_size)
    if after is not None:
        statement = statement.where(Conversation.id > after)
    if only:
        statement = statement.where(Conversation.id.in_([uuid.UUID(value) for value in only]))
    rows = (await session.execute(statement)).all()
    return [EligibleConversation(*row) for row in rows]


async def _blank_lead_count(session: AsyncSession, *, only: list[str] | None = None) -> int:
    statement = select(func.count()).select_from(_blank_lead_statement().subquery())
    if only:
        statement = statement.where(
            Conversation.id.in_([uuid.UUID(value) for value in only])
        )
    return int((await session.scalar(statement)) or 0)


async def _fill_one(
    conversation: EligibleConversation, report: _RunReport
) -> None:
    """Replay one conversation's turns through the live persistence path.

    Its own session, because the persistence path holds a session for the whole
    call and a session must never have two coroutines in flight. Turns stay in
    order: the merge lets the latest non-blank value win, so a conversation
    replayed out of order could let an older answer overwrite a corrected one.
    """
    from app.composition.recruitment import run_candidate_persistence
    from app.graph.client_cache import build_cached_extraction

    try:
        async with get_session_factory()() as session:
            pairs, no_bot, blank = await _conversation_turns(
                session, conversation.conversation_id, include_unanswered=True
            )
            report.turns += len(pairs)
            report.skipped_no_bot += no_bot
            report.skipped_blank += blank
            if not pairs:
                return
            clients = await build_cached_extraction(session)
            for pair in pairs:
                try:
                    await run_candidate_persistence(
                        session,
                        embed_batch=clients.embedder.batch,
                        extractor=clients.extractor,
                        chat_id=conversation.psid,
                        user_text=pair.user_text,
                        bot_output=pair.bot_output,
                        expected_conversation_version=None,
                        contact_id=str(conversation.contact_id),
                        conversation_id=str(conversation.conversation_id),
                    )
                    report.pairs_applied += 1
                except Exception:
                    report.pair_failures += 1
                    logger.warning(
                        "candidate detail fill failed conversation=%s",
                        conversation.conversation_id,
                        exc_info=True,
                    )
    except Exception:
        report.pair_failures += 1
        logger.warning(
            "candidate detail fill aborted conversation=%s",
            conversation.conversation_id,
            exc_info=True,
        )


def _bounded_concurrency(requested: int) -> int:
    """Clamp in-flight conversations to the DB pool this process actually has.

    ``_fill_one`` holds one session for a conversation's whole history, so N in
    flight means N checked-out connections. Asking for more than the pool holds
    does not merely slow the run down, it ends it: every task past the ceiling
    raises QueuePool TimeoutError and the run dies mid-backfill. One connection
    is reserved so the page query that feeds the next batch can still be served.
    """
    from app.core.config import get_settings

    settings = get_settings()
    capacity = settings.db_pool_size + settings.db_max_overflow
    bounded = max(1, min(requested, capacity - 1))
    if bounded != requested:
        logger.warning(
            "concurrency %d exceeds the %d-connection pool; using %d",
            requested,
            capacity,
            bounded,
        )
    return bounded


async def _run(args: argparse.Namespace) -> _RunReport:
    only = list(args.conversation_ids) or None
    concurrency = _bounded_concurrency(args.concurrency)
    async with get_session_factory()() as session:
        eligible_at_start = await _blank_lead_count(session, only=only)
    report = _RunReport(
        run_id=uuid.uuid4().hex,
        dry_run=bool(args.dry_run),
        eligible_at_start=eligible_at_start,
    )
    _emit("start", report.run_id, dry_run=report.dry_run, eligible=eligible_at_start)

    # The same lock as the replay sweep, deliberately: both scripts write the
    # same leads, so they must never run at the same time (one would re-extract
    # what the other just wrote, at double the provider cost).
    async with _exclusive_backfill() as acquired:
        report.lock_acquired = acquired
        if not acquired:
            _emit("locked", report.run_id)
            _emit("final", report.run_id, **report.as_payload())
            return report

        cursor: uuid.UUID | None = None
        batch_number = 0
        pending: list[asyncio.Task[None]] = []
        while args.limit == 0 or report.processed < args.limit:
            page_size = args.batch_size
            if args.limit:
                page_size = min(page_size, args.limit - report.processed)
            async with get_session_factory()() as session:
                page = await _blank_lead_page(
                    session, after=cursor, batch_size=page_size, only=only
                )
            if not page:
                break
            batch_number += 1
            for conversation in page:
                report.processed += 1
                if args.dry_run:
                    continue
                pending.append(
                    asyncio.create_task(_fill_one(conversation, report))
                )
                # Keep a bounded number in flight: the Redis semaphores cap the
                # provider calls, but an unbounded task list would still open a
                # session and hold a conversation's turns in memory per entry.
                if len(pending) >= concurrency:
                    await asyncio.gather(*pending)
                    pending.clear()
            cursor = page[-1].conversation_id
            _emit(
                "batch",
                report.run_id,
                batch=batch_number,
                processed=report.processed,
                turns=report.turns,
                applied=report.pairs_applied,
                failures=report.pair_failures,
            )
        if pending:
            await asyncio.gather(*pending)

    report.limit_reached = bool(args.limit and report.processed >= args.limit)
    _emit("final", report.run_id, **report.as_payload())
    return report


def _emit(event: str, run_id: str, **values: object) -> None:
    print(json.dumps({"event": event, "run_id": run_id, **values}, sort_keys=True), flush=True)


def _exit_code(args: argparse.Namespace, report: _RunReport) -> int:
    if args.dry_run:
        return 0
    if not report.lock_acquired:
        return 3
    if report.pair_failures > 0:
        return 2
    return 0


async def _main(args: argparse.Namespace) -> int:
    try:
        return _exit_code(args, await _run(args))
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
