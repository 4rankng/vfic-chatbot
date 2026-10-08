"""Conversation bot-turn scheduling helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def enqueue_latest_unanswered_worker_message(
    svc,
    conv,
    *,
    enqueue: Callable[[dict], bool | None],
    execution_source: str = "queued",
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
            "reply_to_message_id": pending.zalo_message_id or "",
            "lock_owner": str(lock_owner),
            "execution_source": execution_source,
            "received_at": pending.created_at.isoformat(),
            "received_at_epoch": time.time(),
        }
    )
    if not enqueued:
        await svc.release_lock(conv, lock_owner=lock_owner)
        logger.warning("release enqueue failed for conversation %s; lock released", conv.id)
        return False
    return True


async def enqueue_manual_bot_turn(
    svc,
    conv,
    *,
    enqueue: Callable[[dict], bool | None],
    execution_source: str = "manual",
) -> bool:
    """Enqueue a recruiter-requested turn: read the conversation, reply if warranted.

    Unlike :func:`enqueue_latest_unanswered_worker_message` this needs no pending
    inbound, so it covers the threads where the candidate is waiting on a real
    answer but every inbound already has a reply (the bot answered with a bare
    emoji, for instance) — exactly the case that leaves a recruiter with no lever.

    The job carries no inbound (``user_text`` is empty) and the boolean
    ``manual_turn`` flag; the worker resolves the flag into the agent's directive
    (``app.graph.manual_reply``) so this module never imports the turn runtime.
    """
    lock_owner = await svc.acquire_lock(conv.id)
    if lock_owner is None:
        return False

    now = time.time()
    enqueued = enqueue(
        {
            "conversation_id": str(conv.id),
            "version_at_start": conv.version,
            "user_text": "",
            "user_name": "",
            "reply_to_message_id": "",
            "manual_turn": True,
            "lock_owner": str(lock_owner),
            "execution_source": execution_source,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "received_at_epoch": now,
        }
    )
    if not enqueued:
        await svc.release_lock(conv, lock_owner=lock_owner)
        logger.warning("manual enqueue failed for conversation %s; lock released", conv.id)
        return False
    return True
