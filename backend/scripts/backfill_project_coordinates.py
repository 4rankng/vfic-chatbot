#!/usr/bin/env python3
"""Backfill project work addresses + coordinates for the geo-distance feature.

Runs the same extraction the ingest pipeline runs (``refresh_from_kb``) over
every active project: the LLM extracts the work address from the project's
latest uploaded brief, the value is grounded against that brief, and the
geocoder resolves it onto ``projects.latitude``/``longitude``.

Flags:
  --force       re-geocode every active project, including already-resolved ones
                (the stored address is reused; no LLM call).
  --re-extract  ignore the stored address and re-run the LLM extraction; implies
                --force. Use when a project's brief changed its address.

Everything is best-effort per project: a failure is counted, logged, and the
run continues.

Usage: cd backend && .venv/bin/python scripts/backfill_project_coordinates.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select

from app.composition.project_knowledge import build_knowledge_provider_factory
from app.core.db import async_session, engine
from app.models.company import Project
from app.services.geo.project_address import refresh_from_kb
from app.services.integration_settings import IntegrationSettingsService

logger = logging.getLogger("backfill_project_coordinates")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-geocode every active project, including already-resolved ones",
    )
    parser.add_argument(
        "--re-extract",
        action="store_true",
        help="ignore the stored address and re-run the LLM extraction (implies --force)",
    )
    return parser.parse_args(argv)


async def _llm_json(db):
    """The extractor the ingest worker uses, resolved the same way."""
    factory = build_knowledge_provider_factory()
    settings_service = IntegrationSettingsService(db)
    minimax_config = await settings_service.resolve_minimax()
    openrouter_config = await settings_service.resolve_openrouter()
    return factory.json_extractor(
        minimax_api_key=minimax_config.api_key,
        openrouter_api_key=openrouter_config.api_key,
    )


async def run(*, force: bool, re_extract: bool) -> int:
    updated = 0
    skipped = 0
    failed = 0
    try:
        async with async_session() as db:
            llm_json = await _llm_json(db)
            project_ids = list(
                (
                    await db.scalars(
                        select(Project.id)
                        .where(Project.is_active.is_(True))
                        .order_by(Project.name)
                    )
                ).all()
            )
            for project_id in project_ids:
                try:
                    if re_extract:
                        project = await db.get(Project, project_id)
                        if project is not None:
                            project.extracted_address = None
                            await db.commit()
                    await refresh_from_kb(
                        db, project_id, llm_json=llm_json, force=force or re_extract
                    )
                    await db.commit()
                    project = await db.get(Project, project_id)
                    if project is not None and project.latitude is not None:
                        updated += 1
                        print(
                            f"  ok    {project.name}: {project.extracted_address!r} -> "
                            f"({project.latitude}, {project.longitude})"
                        )
                    else:
                        skipped += 1
                        print(
                            f"  skip  project_id={project_id}: no grounded address/coordinates"
                        )
                except Exception as exc:  # noqa: BLE001 — one project must not stop the run
                    await db.rollback()
                    failed += 1
                    logger.warning("backfill failed project_id=%s", project_id, exc_info=True)
                    print(f"  FAIL  project_id={project_id}: {type(exc).__name__}: {exc}")
    finally:
        # Must run inside this loop: pooled asyncpg connections belong to it.
        await engine.dispose()
    print(f"updated={updated} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    return asyncio.run(run(force=args.force, re_extract=args.re_extract))


if __name__ == "__main__":
    sys.exit(main())
