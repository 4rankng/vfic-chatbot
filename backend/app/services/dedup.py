"""Message deduplication (8-second window).

Zalo retries delivery, so the same msg_id can arrive twice within seconds. We claim
atomically: insert into message_dedup(chat_id, msg_hash); if it already exists (and
is within the window), it's a duplicate and the run is skipped.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dedup_repository import MessageDedupRepository

DEDUP_WINDOW_SECONDS = 8


class MessageDedupService:
    @staticmethod
    async def claim(db: AsyncSession, chat_id: str, msg_hash: str) -> bool:
        """Return True if this is the first time we see (chat_id, msg_hash) in the
        window, False if it's a duplicate."""
        repo = MessageDedupRepository(db)
        await repo.delete_expired(chat_id, DEDUP_WINDOW_SECONDS)
        rowcount = await repo.insert_claim(chat_id, msg_hash)
        await db.commit()
        return rowcount == 1
