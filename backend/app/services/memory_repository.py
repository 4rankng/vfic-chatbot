"""Data-access layer for the memory store (``memories`` table).

Encapsulates the raw SQL ``MemoryService`` previously ran inline (canonical-key
lookup + batched vector INSERT). NO business logic, NO embedder calls — the service
computes embeddings + canonical-key dedup; this repo only persists. Does not commit;
the owning service controls the transaction boundary.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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

    async def insert_memories(self, rows: list[tuple[str, str, str]]) -> None:
        """Batched insert of ``(content, metadata_json, embedding_literal)`` rows."""
        await self.db.execute(
            text(
                "INSERT INTO memories(content, metadata, embedding) "
                "VALUES (:c, CAST(:m AS jsonb), CAST(:e AS vector))"
            ),
            [{"c": c, "m": m, "e": e} for c, m, e in rows],
        )


__all__ = ["MemoryRepository"]
