"""Conversation bot-turn scheduling helpers."""
from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


async def enqueue_latest_unanswered_worker_message(
    svc,
    conv,
    *,
    enqueue: Callable[[dict], bool],
) -> bool:
    """Enqueue a bot turn for the latest unanswered worker message, if any."""
    pending = await svc.latest_unanswered_worker_message(conv)
    if pending is None:
        return False
    lock_owner = await svc.acquire_lock(conv.id)
    if lock_owner is None:
        return False

    enqueued = enqueue(
        {
            "conversation_id": str(conv.id),
            "version_at_start": conv.version,
            "user_text": pending.body,
            "user_name": "",
            "lock_owner": str(lock_owner),
            "received_at": pending.created_at.isoformat(),
        }
    )
    if not enqueued:
        await svc.release_lock(conv, lock_owner=lock_owner)
        logger.warning("release enqueue failed for conversation %s; lock released", conv.id)
        return False
    return True
