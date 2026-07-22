#!/usr/bin/env python3
"""Backfill missing Zalo OA profile labels and avatars without touching bot rows."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session, engine
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.lead import Lead

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EligibleProfile:
    zalo_id: str


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0 processes all eligible rows")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.25,
        help="pause between provider calls to protect Zalo (default: 0.25)",
    )
    args = parser.parse_args(argv)
    if args.limit < 0 or args.delay_seconds < 0:
        parser.error("--limit and --delay-seconds must be zero or greater")
    return args


def _missing(column):
    return func.nullif(func.trim(column), "").is_(None)


async def _eligible_profiles(db: AsyncSession, *, limit: int) -> list[EligibleProfile]:
    statement = (
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
        .order_by(Conversation.zalo_chat_id)
    )
    if limit:
        statement = statement.limit(limit)
    return [EligibleProfile(zalo_id=value) for value in (await db.scalars(statement)).all()]


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
        )


async def _run(args: argparse.Namespace) -> dict[str, int | bool]:
    async with async_session() as db:
        candidates = await _eligible_profiles(db, limit=args.limit)
    report: dict[str, int | bool] = {
        "dry_run": bool(args.dry_run),
        "eligible": len(candidates),
        "attempted": 0,
        "enriched": 0,
        "unchanged": 0,
        "failed": 0,
    }
    if args.dry_run:
        return report
    for candidate in candidates:
        report["attempted"] += 1
        try:
            if await _enrich_one(candidate.zalo_id):
                report["enriched"] += 1
            else:
                report["unchanged"] += 1
        except Exception as exc:  # noqa: BLE001 -- one profile must not stop the sweep
            report["failed"] += 1
            logger.warning("oa profile backfill failed error_type=%s", type(exc).__name__)
        if args.delay_seconds:
            await asyncio.sleep(args.delay_seconds)
    return report


async def _main(args: argparse.Namespace) -> int:
    try:
        print(json.dumps(await _run(args), sort_keys=True))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
