"""Composition root for reporting queries."""

from __future__ import annotations

from app.reporting.application.conversation_attention import (
    list_attention_conversations,
)
from app.reporting.infrastructure.conversation_attention import (
    SqlAlchemyConversationAttentionAdapter,
)


async def run_conversation_attention_query(
    db,
    *,
    viewer,
    reason: str,
    channel_provider: str | None,
    page: int,
    per_page: int,
):
    return await list_attention_conversations(
        SqlAlchemyConversationAttentionAdapter(db, viewer),
        reason=reason,
        channel_provider=channel_provider,
        page=page,
        per_page=per_page,
    )


__all__ = ["run_conversation_attention_query"]
