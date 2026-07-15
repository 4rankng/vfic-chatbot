"""Realtime seam for conversation state changes.

The single place conversation/message realtime events are published. Extracts the
``publish_event(...)`` calls that were duplicated across every state transition in
``ConversationService``. Identical channels + payloads — just one definition now.
"""

from __future__ import annotations

import asyncio
import logging

from app.schemas.conversation import ConversationOut, MessageOut
from app.services.realtime import publish_event

logger = logging.getLogger(__name__)


def _conv_payload(conv) -> dict:
    """Serialize a conversation for the realtime `conversation.updated` payload.

    Shape is consumed verbatim by the frontend SSE/Socket.IO client — do not change.
    """
    return ConversationOut.model_validate(conv).model_dump(mode="json")


def _message_payload(msg) -> dict:
    """Serialize a message for the realtime `message.created` payload."""
    return MessageOut.model_validate(msg).model_dump(mode="json")


class ConversationEventBus:
    """Publishes conversation/message realtime events."""

    def __init__(self, db) -> None:
        self.db = db

    async def conversation_updated(self, conv) -> None:
        await publish_event("conversation.updated", _conv_payload(conv))

    async def message_created(self, msg, conv) -> None:
        await publish_event(
            "message.created",
            {
                "message_id": msg.id,
                "conversation_id": str(conv.id),
                "message": _message_payload(msg),
            },
        )

    def schedule_realtime(self, msg, conv) -> None:
        """Fire-and-forget the post-commit realtime publishes for a new message.

        Payloads are serialized EAGERLY on the caller's coroutine; only the Redis
        publishes are deferred to a background task. This is required for
        correctness: ``expire_on_commit`` invalidates ``msg``/``conv`` after the
        commit in ``record_bot_pending``, so serializing them triggers lazy
        refreshes. Those refreshes are safe on the main greenlet but raise
        ``MissingGreenlet`` from a background task, which corrupts the shared
        session (``PendingRollbackError``) for the rest of the turn. Build here,
        publish there. The task is never awaited; with no running loop (a sync
        test path) the publishes are skipped rather than raising.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            message_payload = {
                "message_id": msg.id,
                "conversation_id": str(conv.id),
                "message": _message_payload(msg),
            }
            conversation_payload = _conv_payload(conv)
        except Exception:
            logger.warning(
                "realtime payload serialization failed; skipping publish",
                exc_info=True,
            )
            return

        async def _emit() -> None:
            await publish_event("message.created", message_payload)
            await publish_event("conversation.updated", conversation_payload)

        loop.create_task(_emit())
