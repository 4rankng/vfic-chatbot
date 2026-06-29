"""Realtime seam for conversation state changes.

The single place conversation/message realtime events are published. Extracts the
``publish_event(...)`` calls that were duplicated across every state transition in
``ConversationService``. Identical channels + payloads — just one definition now.
"""
from __future__ import annotations

from app.schemas.conversation import ConversationOut, MessageOut
from app.services.realtime import publish_event


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
