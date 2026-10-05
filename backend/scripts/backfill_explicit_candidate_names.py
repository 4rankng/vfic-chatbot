#!/usr/bin/env python3
"""Backfill candidate names the inbound explicit-name capture never persisted.

The inbound path (``app/services/webhook.py``) captures a self-introduced name
deterministically — an explicit "mình tên X", or a bare reply to the bot's name
question — and does not wait for the deferred LLM extraction. Two defects made
that capture a no-op in production:

* the history look-back walked ``repo.last_messages`` (newest-first) through
  ``reversed(...)``, so ``prev_bot_message`` was the OLDEST bot turn in the
  five-message window instead of the one that asked for the name. A bare reply
  such as "Bùi thị hòa" therefore never matched its own request.
* the write was Zalo-chat-id keyed only. A Messenger conversation has
  ``zalo_chat_id IS NULL``, so ``normalize_lead`` built a ``leads.zalo_id`` patch
  that could not address its (contact-keyed) lead row.

Both are fixed in the application code; this script repairs the data they lost.
It replays the SAME deterministic extractor over stored history — no model call,
no provider round trip — and writes only when the candidate's own words plus the
bot's immediately preceding question make the name unambiguous. The lead merge is
blank-only and idempotent, so a recruiter-filled name is never overwritten and a
re-run writes nothing new.

    python -m scripts.backfill_explicit_candidate_names --days 2           # plan
    python -m scripts.backfill_explicit_candidate_names --days 2 --apply   # write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session_factory
from app.models.conversation import Conversation, Message
from app.recruitment.domain.provider import lead_key_for_conversation
from app.services.lead.normalizers import extract_self_reported_name, normalize_lead
from app.services.lead.repository import LeadRepository
from scripts.backfill_messenger_candidates import _exclusive_backfill

logger = logging.getLogger(__name__)


@dataclass
class _RunReport:
    """Mutable counters for one run."""

    run_id: str
    apply: bool = False
    scanned: int = 0
    already_named: int = 0
    no_evidence: int = 0
    no_lead_key: int = 0
    names_found: int = 0
    written: int = 0
    write_failures: int = 0
    lock_acquired: bool = False

    def as_payload(self) -> dict:
        return {
            "scanned": self.scanned,
            "already_named": self.already_named,
            "no_evidence": self.no_evidence,
            "no_lead_key": self.no_lead_key,
            "names_found": self.names_found,
            "written": self.written,
            "write_failures": self.write_failures,
            "lock_acquired": self.lock_acquired,
        }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=2, help="only conversations with inbound in the last N days"
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the names (default: report only)"
    )
    parser.add_argument("--limit", type=int, default=0, help="process at most N conversations")
    parser.add_argument(
        "--conversation-id",
        action="append",
        default=[],
        dest="conversation_ids",
        help="Restrict the run to this conversation id (repeatable).",
    )
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")
    return args


def name_from_history(rows: list[tuple[object, str | None]]) -> str | None:
    """The candidate's self-introduced name from one conversation's messages.

    ``rows`` must be chronological. Each candidate turn is judged against the bot
    message that immediately preceded it, exactly as the inbound path does, so a
    bare token is read as a name only when the bot had just asked for one. The
    first unambiguous name wins: later turns usually echo it back.
    """
    previous_bot: str | None = None
    for sender, body in rows:
        role = str(getattr(sender, "value", sender))
        if role == "BOT":
            previous_bot = body
            continue
        if role != "WORKER":
            continue
        name = extract_self_reported_name(body, prev_bot_message=previous_bot)
        if name:
            return name
    return None


def _eligible_statement(args: argparse.Namespace):
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    statement = (
        select(Conversation.id, Conversation.contact_id, Conversation.zalo_chat_id)
        .where(Conversation.last_inbound_at >= since)
        .order_by(Conversation.id)
    )
    if args.conversation_ids:
        statement = statement.where(
            Conversation.id.in_([uuid.UUID(value) for value in args.conversation_ids])
        )
    if args.limit:
        statement = statement.limit(args.limit)
    return statement


async def _history(session: AsyncSession, conversation_id) -> list[tuple[object, str | None]]:
    rows = (
        await session.execute(
            select(Message.sender, Message.body)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    ).all()
    return [(sender, body) for sender, body in rows]


async def _fill_one(session: AsyncSession, conversation, report: _RunReport) -> None:
    """Persist one conversation's captured name when its lead has none yet."""
    report.scanned += 1
    lead_key = lead_key_for_conversation(conversation)
    if not lead_key.is_writable:
        report.no_lead_key += 1
        return
    repo = LeadRepository(session)
    existing = (
        await repo.by_contact_id(lead_key.contact_id)
        if lead_key.contact_id
        else await repo.by_zalo_id(lead_key.zalo_id)
    )
    if str((existing or {}).get("name") or "").strip():
        report.already_named += 1
        return
    name = name_from_history(await _history(session, conversation.id))
    if not name:
        report.no_evidence += 1
        return
    report.names_found += 1
    _emit("name_found", report.run_id, conversation_id=str(conversation.id), name=name)
    if not report.apply:
        return
    patch = normalize_lead({"name": name}, lead_key.zalo_id or lead_key.contact_id)
    if patch is None:
        report.no_lead_key += 1
        return
    try:
        if lead_key.contact_id and not lead_key.zalo_id:
            await repo.upsert_by_contact(lead_key.contact_id, patch)
        else:
            await repo.upsert(patch)
        await session.commit()
        report.written += 1
        _emit("name_written", report.run_id, conversation_id=str(conversation.id), name=name)
    except Exception:
        await session.rollback()
        report.write_failures += 1
        logger.warning(
            "name backfill write failed conversation=%s", conversation.id, exc_info=True
        )


def _emit(event: str, run_id: str, **values: object) -> None:
    print(json.dumps({"event": event, "run_id": run_id, **values}, sort_keys=True), flush=True)


async def _run(args: argparse.Namespace) -> _RunReport:
    report = _RunReport(run_id=uuid.uuid4().hex, apply=bool(args.apply))
    async with _exclusive_backfill() as acquired:
        report.lock_acquired = acquired
        if not acquired:
            _emit("skipped_locked", report.run_id)
            return report
        _emit("start", report.run_id, apply=report.apply, days=args.days)
        async with get_session_factory()() as session:
            for conversation in (await session.execute(_eligible_statement(args))).all():
                await _fill_one(session, conversation, report)
    _emit("done", report.run_id, **report.as_payload())
    return report


def _exit_code(args: argparse.Namespace, report: _RunReport) -> int:
    if not report.lock_acquired:
        return 3
    if report.write_failures:
        return 2
    return 0


async def _main(args: argparse.Namespace) -> int:
    report = await _run(args)
    return _exit_code(args, report)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
