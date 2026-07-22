#!/usr/bin/env python3
"""Resumable, observable backfill for missing Zalo OA profile fields."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session, engine
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.lead import Lead

logger = logging.getLogger(__name__)

_BACKFILL_ADVISORY_LOCK_KEY = 0x564649434F415052


@dataclass(frozen=True)
class EligibleProfile:
    zalo_id: str


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0 processes all eligible rows")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.limit < 0 or args.delay_seconds < 0 or args.retry_delay_seconds < 0:
        parser.error("limits and delays must be zero or greater")
    if args.batch_size < 1 or args.max_attempts < 1:
        parser.error("--batch-size and --max-attempts must be at least 1")
    return args


def _missing(column):
    return func.nullif(func.trim(column), "").is_(None)


def _eligible_statement():
    return (
        select(Conversation.zalo_chat_id)
        .join(Contact, Contact.id == Conversation.contact_id)
        .join(Lead, Lead.contact_id == Contact.id)
        .where(
            Conversation.zalo_channel == "oa",
            Conversation.zalo_chat_id.is_not(None),
            Conversation.zalo_chat_id.like("oa:%"),
            or_(
                _missing(Contact.display_name),
                _missing(Contact.avatar_url),
                _missing(Lead.avatar_url),
            ),
        )
        .distinct()
    )


async def _eligible_profiles_page(
    db: AsyncSession,
    *,
    after: str | None,
    batch_size: int,
) -> list[EligibleProfile]:
    statement = _eligible_statement()
    if after is not None:
        statement = statement.where(Conversation.zalo_chat_id > after)
    statement = statement.order_by(Conversation.zalo_chat_id).limit(batch_size)
    return [EligibleProfile(zalo_id=value) for value in (await db.scalars(statement)).all()]


async def _eligible_count(db: AsyncSession) -> int:
    statement = select(func.count()).select_from(_eligible_statement().subquery())
    return int(await db.scalar(statement) or 0)


async def _profile_still_missing(zalo_id: str) -> bool:
    async with async_session() as db:
        statement = _eligible_statement().where(Conversation.zalo_chat_id == zalo_id).limit(1)
        return (await db.scalar(statement)) is not None


async def _enrich_one(zalo_id: str) -> bool:
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.profile_enrichment import ProfileEnrichmentService
    from app.services.zalo_oa_service import ZaloOASender

    async with async_session() as db:
        integration = IntegrationSettingsService(db)
        config = await integration.resolve_zalo()
        sender = ZaloOASender(
            access_token=config.oa_access_token,
            refresh=integration.refresh_oa_access_token,
        )
        return await ProfileEnrichmentService(db, sender).enrich_oa_user(
            zalo_id,
            user_id=zalo_id.removeprefix("oa:"),
            wait_for_inflight=True,
            force_lookup=True,
        )


@asynccontextmanager
async def _exclusive_backfill() -> AsyncIterator[bool]:
    """Hold a crash-safe PostgreSQL session advisory lock for the whole run."""
    async with engine.connect() as connection:
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


async def _process_profile(
    zalo_id: str,
    *,
    max_attempts: int,
    retry_delay_seconds: float,
) -> tuple[bool, bool]:
    """Return ``(complete, changed)`` after bounded retries."""
    changed = False
    for attempt in range(1, max_attempts + 1):
        try:
            changed = await _enrich_one(zalo_id) or changed
        except Exception as exc:  # noqa: BLE001 -- one profile must not stop the run
            logger.warning("oa profile backfill attempt failed error_type=%s", type(exc).__name__)
        try:
            if not await _profile_still_missing(zalo_id):
                return True, changed
        except Exception as exc:  # noqa: BLE001 -- retry transient checkpoint failures
            logger.warning(
                "oa profile backfill checkpoint failed error_type=%s", type(exc).__name__
            )
        if attempt < max_attempts and retry_delay_seconds:
            await asyncio.sleep(retry_delay_seconds * (2 ** (attempt - 1)))
    return False, changed


async def _run(args: argparse.Namespace) -> dict[str, int | bool | str]:
    run_id = uuid.uuid4().hex
    async with async_session() as db:
        eligible_at_start = await _eligible_count(db)
    report: dict[str, int | bool | str] = {
        "run_id": run_id,
        "dry_run": bool(args.dry_run),
        "lock_acquired": False,
        "eligible_at_start": eligible_at_start,
        "attempted": 0,
        "completed": 0,
        "changed": 0,
        "failed": 0,
        "remaining": eligible_at_start,
        "limit_reached": False,
    }
    _emit("start", run_id, dry_run=bool(args.dry_run), eligible=eligible_at_start)
    if args.dry_run:
        _emit("final", run_id, **{key: value for key, value in report.items() if key != "run_id"})
        return report

    async with _exclusive_backfill() as acquired:
        report["lock_acquired"] = acquired
        if not acquired:
            _emit("locked", run_id)
            _emit(
                "final",
                run_id,
                **{key: value for key, value in report.items() if key != "run_id"},
            )
            return report

        cursor: str | None = None
        batch_number = 0
        while args.limit == 0 or int(report["attempted"]) < args.limit:
            page_size = args.batch_size
            if args.limit:
                page_size = min(page_size, args.limit - int(report["attempted"]))
            async with async_session() as db:
                page = await _eligible_profiles_page(db, after=cursor, batch_size=page_size)
            if not page:
                break
            batch_number += 1
            for candidate in page:
                complete, changed = await _process_profile(
                    candidate.zalo_id,
                    max_attempts=args.max_attempts,
                    retry_delay_seconds=args.retry_delay_seconds,
                )
                report["attempted"] = int(report["attempted"]) + 1
                report["completed" if complete else "failed"] = (
                    int(report["completed" if complete else "failed"]) + 1
                )
                if changed:
                    report["changed"] = int(report["changed"]) + 1
                if args.delay_seconds:
                    await asyncio.sleep(args.delay_seconds)
            cursor = page[-1].zalo_id
            _emit(
                "batch",
                run_id,
                batch=batch_number,
                attempted=report["attempted"],
                completed=report["completed"],
                failed=report["failed"],
            )

        async with async_session() as db:
            report["remaining"] = await _eligible_count(db)
        report["limit_reached"] = bool(
            args.limit and int(report["attempted"]) >= args.limit and int(report["remaining"]) > 0
        )

    _emit("final", run_id, **{key: value for key, value in report.items() if key != "run_id"})
    return report


def _exit_code(args: argparse.Namespace, report: dict[str, int | bool | str]) -> int:
    if args.dry_run:
        return 0
    if not report["lock_acquired"]:
        return 3
    if int(report["failed"]) > 0:
        return 2
    if not report["limit_reached"] and int(report["remaining"]) > 0:
        return 2
    return 0


async def _main(args: argparse.Namespace) -> int:
    try:
        return _exit_code(args, await _run(args))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
