"""Direct-turn lease renewal safety tests."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.conversation.state import ConversationState


@pytest.mark.asyncio
async def test_renew_lock_rejects_an_expired_lease_even_for_same_owner() -> None:
    """The owner token alone must never revive a lease after its TTL expired."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    db.commit = AsyncMock()
    state = ConversationState(db, MagicMock(), AsyncMock())

    renewed = await state.renew_lock(uuid.uuid4(), lock_owner=uuid.uuid4())

    assert renewed is False
    query = str(db.execute.call_args.args[0])
    assert "bot_locked_until >" in query
