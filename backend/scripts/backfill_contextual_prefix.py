#!/usr/bin/env python3
"""Backfill the Contextual Retrieval prefix into existing knowledge chunks.

New ingests embed every digest chunk under its document-context prefix
(``app.services.knowledge.contextual``). Chunks indexed before the feature
carry unprefixed vectors, so they never benefit from it until re-embedded.
This script rebuilds each eligible chunk's embed input exactly as the live
pipeline would (prefix + content + summary + questions), re-embeds it with the
configured provider, and updates ``embedding`` plus
``metadata.contextual_prefix`` — ``content`` stays verbatim.

Eligible = document chunks that are visible (document not ARCHIVED/FAILED),
have an embedding, are not category-revision records (their indexing path is
unchanged by the feature), are not canonical chunks (those already embed their
spec-owned ``contextual_text`` header), and carry no prefix yet — so the run
is idempotent.

Usage::

    python -m scripts.backfill_contextual_prefix                # live run
    python -m scripts.backfill_contextual_prefix --dry-run      # plan only
    python -m scripts.backfill_contextual_prefix --limit 500    # bounded batch

Per-document commit for resumability. Never logs chunk content — only ids,
counts and the bounded prefix lengths.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from app.services.knowledge.contextual import (
    CONTEXTUAL_PREFIX_VERSION,
    contextual_embed_input,
    contextual_enabled,
)

logger = logging.getLogger(__name__)

# Rows processed per SELECT batch. Bounded so a huge table streams instead of
# loading every content blob into memory at once.
BATCH_SIZE = 200


async def _fetch_pending_batch(db, *, after_document: uuid.UUID | None) -> list:
    """One ordered batch of ``(chunk_id, document_id, file_name, digest_summary,
    content, summary, questions, metadata)`` rows still missing the prefix."""
    from sqlalchemy import text

    # Keyset pagination on (document_id, chunk_index): ORDER BY document_id
    # then chunk_index, resuming after the last processed document.
    where_extra = ""
    params: dict[str, object] = {"batch": BATCH_SIZE}
    if after_document is not None:
        where_extra = "AND c.document_id > CAST(:after AS uuid) "
        params["after"] = str(after_document)
    rows = (
        await db.execute(
            text(
                "SELECT c.id, c.document_id, d.file_name, d.digest_summary, "
                "       c.content, c.summary, c.questions, c.metadata, c.category, "
                "       c.chunk_index "
                "FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON d.id = c.document_id "
                "WHERE d.status NOT IN ('ARCHIVED', 'FAILED') "
                "AND c.embedding IS NOT NULL "
                "AND c.category_revision_id IS NULL "
                "AND (c.metadata IS NULL OR ("
                "     NOT (c.metadata ? 'contextual_prefix') "
                "     AND NOT (c.metadata ? 'chunk_metadata'))) "
                + where_extra
                + "ORDER BY c.document_id, c.chunk_index "
                "LIMIT :batch"
            ),
            params,
        )
    ).all()
    return list(rows)


async def _apply_prefix(db, chunk_id, prefix: str, emb_literal: str) -> None:
    from sqlalchemy import text

    await db.execute(
        text(
            "UPDATE knowledge_chunks "
            "SET embedding = CAST(:emb AS vector), "
            "    metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), "
            "                         '{contextual_prefix}', "
            "                         to_jsonb(CAST(:prefix AS text))) "
            "WHERE id = CAST(:cid AS uuid)"
        ),
        {"emb": emb_literal, "prefix": prefix, "cid": str(chunk_id)},
    )


async def _backfill(*, dry_run: bool, limit: int | None) -> None:
    from app.core.vector import vec_literal

    from app.graph.clients import build_embedder
    from app.services.integration_settings import IntegrationSettingsService
    from app.workers._db import worker_session

    if not contextual_enabled():
        logger.error(
            "rag_contextual_enabled is off — a backfill would write prefixes "
            "the serving config does not index with. Enable the toggle first."
        )
        return

    total = 0
    last_document: uuid.UUID | None = None
    async with worker_session() as db:
        integration_settings = IntegrationSettingsService(db)
        openrouter_config = await integration_settings.resolve_openrouter()
        embed = build_embedder(openrouter_api_key=openrouter_config.api_key)

        while limit is None or total < limit:
            rows = await _fetch_pending_batch(db, after_document=last_document)
            if not rows:
                break
            # Group by document: one embed batch + one commit per document so
            # an interrupted run leaves whole documents consistent.
            by_document: dict[uuid.UUID, list] = {}
            for row in rows:
                doc_id = uuid.UUID(str(row.document_id))
                by_document.setdefault(doc_id, []).append(row)
                last_document = doc_id
            for doc_id, doc_rows in by_document.items():
                file_name = str(doc_rows[0].file_name or "")
                digest_summary = str(doc_rows[0].digest_summary or "") or None
                if dry_run:
                    logger.info(
                        "[dry-run] document=%s file=%s chunks=%d",
                        doc_id,
                        file_name,
                        len(doc_rows),
                    )
                    total += len(doc_rows)
                    continue
                embed_inputs = []
                prefixes = []
                for row in doc_rows:
                    unit: dict = {
                        "summary": row.summary,
                        "source_anchor": (row.metadata or {}).get("source_anchor"),
                        "category": row.category,
                    }
                    # Mirror _store_units exactly: prefix rides in front of
                    # the content; the unit's summary + questions follow as
                    # their own lines of the combined embed input.
                    prefixed_content = contextual_embed_input(
                        unit,
                        str(row.content or ""),
                        doc_title=file_name,
                        doc_summary=digest_summary,
                    )
                    tail = [
                        str(part)
                        for part in (row.summary, *list(row.questions or []))
                        if part
                    ]
                    embed_inputs.append("\n".join([prefixed_content, *tail]))
                    prefixes.append(unit.get("contextual_prefix"))
                vectors = await embed.batch(embed_inputs)
                if len(vectors) != len(doc_rows):
                    raise RuntimeError(
                        f"embedding mismatch on document={doc_id}: "
                        f"{len(vectors)} vectors for {len(doc_rows)} chunks"
                    )
                for row, prefix, vector in zip(doc_rows, prefixes, vectors, strict=True):
                    await _apply_prefix(db, row.id, prefix or "", vec_literal(vector))
                    total += 1
                await db.commit()
                logger.info(
                    "prefixed document=%s file=%s chunks=%d prefix_version=%s",
                    doc_id,
                    file_name,
                    len(doc_rows),
                    CONTEXTUAL_PREFIX_VERSION,
                )
            if dry_run and len(rows) < BATCH_SIZE:
                break
    logger.info("backfill complete: %d chunks prefixed (dry_run=%s)", total, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="List target documents without writing"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Stop after this many chunks"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_backfill(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
