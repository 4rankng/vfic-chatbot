#!/usr/bin/env python3
"""Backfill ``direct_context`` chunks for existing DIRECT_CONTEXT projects.

Phase 5 of plan ``260722-2300-cross-kb-retrieval-and-stats``. Existing DIRECT_CONTEXT
projects have their content only in ``knowledge_base_direct_files`` (invisible to
``search_knowledge``). This script re-indexes them via the shared pipeline so
``chunk_type='direct_context'`` chunks exist and participate in cross-project retrieval.

Usage::

    python -m scripts.backfill_direct_context_chunks            # live run
    python -m scripts.backfill_direct_context_chunks --dry-run   # print plan only

Per-project commit for resumability. Idempotent (the indexing path is find-or-create +
``replace_for_doc``). Never logs chunk content.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


async def _iter_direct_context_projects(db) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    """Return ``(kb_id, project_id, text_blob)`` for every DIRECT_CONTEXT KB."""
    from sqlalchemy import text

    rows = (
        await db.execute(
            text(
                "SELECT kb.id, p.id, COALESCE(df.normalized_text, df.raw_text, '') "
                "FROM knowledge_bases kb "
                "JOIN projects p ON p.knowledge_base_id = kb.id "
                "LEFT JOIN knowledge_base_direct_files df "
                "  ON df.knowledge_base_id = kb.id "
                "WHERE kb.mode = 'DIRECT_CONTEXT' AND p.is_active"
            )
        )
    ).all()
    return [(uuid.UUID(str(r[0])), uuid.UUID(str(r[1])), str(r[2] or "")) for r in rows]


async def _backfill(*, dry_run: bool) -> None:
    from app.graph.clients import build_embedder
    from app.graph.factories import make_minimax_llm_json
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.knowledge.direct_context_indexing import index_direct_context
    from app.workers._db import worker_session

    total = 0
    async with worker_session() as db:
        targets = await _iter_direct_context_projects(db)
        logger.info("found %d DIRECT_CONTEXT projects", len(targets))
        if dry_run:
            for kb_id, project_id, text_blob in targets:
                logger.info(
                    "[dry-run] kb=%s project=%s chars=%d", kb_id, project_id, len(text_blob)
                )
            return

        integration_settings = IntegrationSettingsService(db)
        openrouter_config = await integration_settings.resolve_openrouter()
        embed = build_embedder(openrouter_api_key=openrouter_config.api_key)
        minimax_config = await integration_settings.resolve_minimax()
        llm_json = make_minimax_llm_json(
            minimax_api_key=minimax_config.api_key,
            openrouter_api_key=openrouter_config.api_key,
        )

        for kb_id, project_id, text_blob in targets:
            try:
                await index_direct_context(
                    db, kb_id, project_id, text_blob, embedder=embed, llm_json=llm_json
                )
                total += 1
                logger.info("indexed kb=%s project=%s", kb_id, project_id)
            except Exception:  # noqa: BLE001 — keep going; per-project isolation
                logger.exception("failed indexing kb=%s project=%s", kb_id, project_id)
    logger.info("backfill complete: %d/%d projects indexed", total, len(targets))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="List targets without indexing"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_backfill(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
