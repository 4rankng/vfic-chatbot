"""HTTP adapters for conversation messaging routes."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation


async def load_conversation_record(
    db: AsyncSession,
    conv_id: uuid.UUID,
) -> Conversation | None:
    return await db.get(Conversation, conv_id)


__all__ = ["load_conversation_record"]
