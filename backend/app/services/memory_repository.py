"""Data-access layer for the memory store (``memories`` table).

Encapsulates the raw SQL ``MemoryService`` previously ran inline (canonical-key
lookup + batched vector INSERT). NO business logic, NO embedder calls — the service
computes embeddings + canonical-key dedup; this repo only persists. Does not commit;
the owning service controls the transaction boundary.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version


class MemoryRepository:
    """Read/write the ``memories`` table (no ORM model; raw SQL only)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_canonical_keys(self, chat_id: str) -> set[str]:
        """Canonical keys already stored for this chat (the dedup set)."""
        rows = (
            await self.db.execute(
                text(
                    "SELECT metadata->>'canonical_key' AS ck "
                    "FROM memories WHERE metadata->>'chat_id' = :c"
                ),
                {"c": chat_id},
            )
        ).all()
        return {r.ck for r in rows if r.ck}

    async def insert_memories(self, rows: list[tuple[str, str, str]]) -> int:
        """Batched insert of ``(content, metadata_json, embedding_literal)`` rows.

        Returns ``len(rows)`` (the caller pre-deduplicates, so input count equals
        expected inserts).  ``ON CONFLICT DO NOTHING`` guards against race-condition
        duplicate-key errors; asyncpg ``executemany`` rowcount is unreliable, so
        we use the input count rather than ``result.rowcount``.
        """
        await self.db.execute(
            text(
                "INSERT INTO memories(content, metadata, embedding) "
                "VALUES (:c, CAST(:m AS jsonb), CAST(:e AS vector)) "
                "ON CONFLICT DO NOTHING"
            ),
            [{"c": c, "m": m, "e": e} for c, m, e in rows],
        )
        for _content, metadata_json, _embedding in rows:
            try:
                chat_id = json.loads(metadata_json).get("chat_id")
            except Exception:  # noqa: BLE001
                chat_id = None
            if chat_id:
                await bump_cache_version(f"memory:{chat_id}")
        return len(rows)


__all__ = ["MemoryRepository"]
