from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.recruitment.application.persistence import (
    PersistCandidateCommand,
    persist_candidate,
)


@pytest.mark.asyncio
async def test_persist_candidate_forwards_one_neutral_command() -> None:
    result = object()
    port = AsyncMock()
    port.persist.return_value = result
    command = PersistCandidateCommand(
        chat_id="oa:user-1",
        user_text="Tôi tên Mai",
        bot_output="Chào Mai",
        expected_conversation_version=7,
    )

    actual = await persist_candidate(
        port,
        command,
        embed_batch="embedder",
        extractor="extractor",
    )

    assert actual is result
    port.persist.assert_awaited_once_with(
        command,
        embed_batch="embedder",
        extractor="extractor",
    )
