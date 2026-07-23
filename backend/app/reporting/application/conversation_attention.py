"""Read-only conversation attention query orchestration."""

from __future__ import annotations

from typing import Any, Protocol


class ConversationAttentionQueryPort(Protocol):
    async def attention_reason_page(
        self,
        *,
        reason: str,
        channel_provider: str | None,
        page: int,
        per_page: int,
    ) -> tuple[list[Any], int]: ...

    async def visible_conversations(self, ids: list[Any]) -> list[Any]: ...


async def list_attention_conversations(
    port: ConversationAttentionQueryPort,
    *,
    reason: str,
    channel_provider: str | None,
    page: int,
    per_page: int,
) -> tuple[list[Any], int]:
    """Return a viewer-scoped page without coupling write services to reporting."""

    page_ids, total = await port.attention_reason_page(
        reason=reason,
        channel_provider=channel_provider,
        page=page,
        per_page=per_page,
    )
    rows = await port.visible_conversations(page_ids)
    rows_by_id = {row.id: row for row in rows}
    return [rows_by_id[row_id] for row_id in page_ids if row_id in rows_by_id], total


__all__ = ["ConversationAttentionQueryPort", "list_attention_conversations"]
