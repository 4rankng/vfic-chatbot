"""Inbox ordering contract: the default sort is the latest message.

``updated_at`` is unreliable for the inbox — batch maintenance (backfills,
migrations) touches it without a new message, which scrambled the list against
the timestamp each row displays. The default must be the latest candidate
message, falling back to ``updated_at`` only when there is none.
"""

from __future__ import annotations

from app.services.conversation.repository import (
    _CONVERSATION_DEFAULT_SORT,
    _CONVERSATION_SORT,
)


def test_inbox_default_sort_is_the_latest_message() -> None:
    assert _CONVERSATION_DEFAULT_SORT == "last_message_at"
    expression = str(_CONVERSATION_SORT["last_message_at"]).lower()
    assert "coalesce" in expression
    assert "last_inbound_at" in expression
    assert "updated_at" in expression
    # A distinct key from the drift-prone updated_at column.
    assert _CONVERSATION_SORT["last_message_at"] is not _CONVERSATION_SORT["updated_at"]
