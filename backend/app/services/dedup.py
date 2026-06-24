"""Message deduplication (8-second window) — port of the n8n 'Dedup Message' node.

Zalo retries delivery, so the same msg_id can arrive twice within seconds. We claim
atomically: insert into message_dedup(chat_id, msg_hash); if it already exists (and
is within the window), it's a duplicate and the run is skipped.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEDUP_WINDOW_SECONDS = 8


class MessageDedupService:
    @staticmethod
    async def claim(db: AsyncSession, chat_id: str, msg_hash: str) -> bool:
        """Return True if this is the first time we see (chat_id, msg_hash) in the
        window, False if it's a duplicate."""
        await db.execute(
            text(
                "DELETE FROM public.message_dedup "
                "WHERE seen_at < now() - (:secs || ' seconds')::interval "
                "AND chat_id = :c"
            ),
            {"secs": str(DEDUP_WINDOW_SECONDS), "c": chat_id},
        )
        res = await db.execute(
            text(
                "INSERT INTO public.message_dedup(chat_id, msg_hash) VALUES(:c,:h) "
                "ON CONFLICT DO NOTHING"
            ),
            {"c": chat_id, "h": msg_hash},
        )
        await db.commit()
        return res.rowcount == 1
