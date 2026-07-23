from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.reporting.application.conversation_attention import (
    list_attention_conversations,
)


@pytest.mark.asyncio
async def test_attention_query_preserves_projection_order_and_total() -> None:
    first = SimpleNamespace(id="first")
    second = SimpleNamespace(id="second")
    port = SimpleNamespace(
        attention_reason_page=AsyncMock(return_value=(["second", "first"], 7)),
        visible_conversations=AsyncMock(return_value=[first, second]),
    )

    rows, total = await list_attention_conversations(
        port,
        reason="UNREAD",
        channel_provider="zalo_oa",
        page=2,
        per_page=20,
    )

    assert rows == [second, first]
    assert total == 7
    port.attention_reason_page.assert_awaited_once_with(
        reason="UNREAD",
        channel_provider="zalo_oa",
        page=2,
        per_page=20,
    )
    port.visible_conversations.assert_awaited_once_with(["second", "first"])
