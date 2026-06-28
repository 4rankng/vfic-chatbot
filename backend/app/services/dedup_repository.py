"""Data-access layer for the 8-second message-dedup window (``message_dedup`` table)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MessageDedupRepository:
    """Read/write the ``message_dedup`` table (no ORM model; raw SQL only)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def delete_expired(self, chat_id: str, window_seconds: int) -> None:
        """Drop dedup claims older than the window for this chat."""
        await self.db.execute(
            text(
                "DELETE FROM public.message_dedup "
                "WHERE seen_at < now() - (:secs || ' seconds')::interval "
                "AND chat_id = :c"
            ),
            {"secs": str(window_seconds), "c": chat_id},
        )

    async def insert_claim(self, chat_id: str, msg_hash: str) -> int:
        """Atomically claim ``(chat_id, msg_hash)``; return 1 if new, 0 if duplicate."""
        res = await self.db.execute(
            text(
                "INSERT INTO public.message_dedup(chat_id, msg_hash) VALUES(:c,:h) "
                "ON CONFLICT DO NOTHING"
            ),
            {"c": chat_id, "h": msg_hash},
        )
        return res.rowcount


__all__ = ["MessageDedupRepository"]
