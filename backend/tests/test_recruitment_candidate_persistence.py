from __future__ import annotations

from typing import Any

import pytest

from app.recruitment.application.persistence import (
    PersistCandidateCommand,
    persist_candidate,
)


class _RecordingPort:
    """Typed stand-in for ``CandidatePersistencePort``.

    A bare ``AsyncMock()`` is ``Any``, which erases the argument types this file
    exists to pin — the command's fields and the two injected collaborators.
    Recording the calls explicitly keeps the assertions honest.
    """

    def __init__(self) -> None:
        self.result: Any = None
        self.calls: list[tuple[PersistCandidateCommand, Any, Any]] = []

    async def persist(self, command, *, embed_batch, extractor):
        self.calls.append((command, embed_batch, extractor))
        return self.result


@pytest.mark.asyncio
async def test_persist_candidate_forwards_one_neutral_command() -> None:
    result = object()
    port = _RecordingPort()
    port.result = result
    command = PersistCandidateCommand(
        chat_id="oa:user-1",
        user_text="Tôi tên Mai",
        bot_output="Chào Mai",
        expected_conversation_version=7,
        contact_id="contact-1",
        conversation_id="conversation-1",
    )

    actual = await persist_candidate(
        port,
        command,
        embed_batch="embedder",
        extractor="extractor",
    )

    assert actual is result
    assert port.calls == [(command, "embedder", "extractor")]


@pytest.mark.asyncio
async def test_persist_candidate_defaults_the_new_keys_to_none() -> None:
    """A job enqueued before the Messenger fix carries neither key."""
    port = _RecordingPort()
    command = PersistCandidateCommand(
        chat_id="oa:user-1",
        user_text="Tôi tên Mai",
        bot_output="Chào Mai",
    )

    await persist_candidate(
        port,
        command,
        embed_batch="embedder",
        extractor="extractor",
    )

    assert command.contact_id is None
    assert command.conversation_id is None
    assert port.calls == [(command, "embedder", "extractor")]
