"""Message deduplication (8-second window).

Zalo retries delivery, so the same msg_id can arrive twice within seconds. We claim
atomically: insert into message_dedup(chat_id, msg_hash); if it already exists (and
is within the window), it's a duplicate and the run is skipped.

Window sizing: ``DEDUP_WINDOW_SECONDS`` must exceed Zalo's webhook retry interval so
a 503/timeout-triggered retry is absorbed here rather than spawning a second turn.
If a retry ever lands AFTER the window, it is still caught by the second layer — the
per-chat mutex ``Conversation.bot_locked_until`` (acquired in
``ZaloWebhookService.handle`` via ``ConversationState.acquire_lock``), which
serializes a late duplicate into a ``{"status": "locked"}`` no-op instead of a
double-send. Raise the window only if prod logs show retry-driven ``locked`` spikes.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dedup_repository import MessageDedupRepository

DEDUP_WINDOW_SECONDS = 8


class MessageDedupService:
    @staticmethod
    async def claim(
        db: AsyncSession,
        chat_id: str,
        msg_hash: str,
        *,
        commit: bool = True,
    ) -> bool:
        """Return True if this is the first time we see (chat_id, msg_hash) in the
        window, False if it's a duplicate.

        ``commit=False`` lets a caller make the claim part of a larger atomic
        transaction. A rollback then releases the claim so the webhook provider
        can retry safely.
        """
        repo = MessageDedupRepository(db)
        await repo.delete_expired(chat_id, DEDUP_WINDOW_SECONDS)
        rowcount = await repo.insert_claim(chat_id, msg_hash)
        if commit:
            await db.commit()
        return rowcount == 1
