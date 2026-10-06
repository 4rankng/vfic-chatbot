"""Unit pins for the permanent user-unreachable send side effects.

Zalo OA ``-201 user_id is invalid`` and Messenger ``code=551`` never become
deliverable by retrying, so the finalizers stamp the conversation once
(follow-up opt-out + a CRM-visible system note, channel-specific wording).
These pins cover the helper's contract; the finalizer wiring is two
straight-line calls reviewed against the same marker constant.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.conversation import Message
from app.services.conversation.unreachable import (
    _MESSENGER_NOTE_BODY,
    _NOTE_BODY,
    USER_UNREACHABLE_SEND_CLASS,
    apply_user_unreachable_side_effects,
)


class _FakeDb:
    """Records adds; scalar returns the configured existing-note count."""

    def __init__(self, existing_notes: int = 0) -> None:
        self.added: list = []
        self.commits = 0
        self._existing_notes = existing_notes

    async def scalar(self, *_args, **_kwargs) -> int:
        return self._existing_notes

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _conv(channel: str = "oa"):
    return SimpleNamespace(
        id="conv-1", zalo_channel=channel, followup_opted_out=False
    )


@pytest.mark.asyncio
async def test_first_unreachable_failure_stamps_opt_out_and_note():
    db = _FakeDb(existing_notes=0)
    conv = _conv()
    events = SimpleNamespace(conversation_updated=AsyncMock())

    await apply_user_unreachable_side_effects(db, conv, events)

    assert conv.followup_opted_out is True
    assert len(db.added) == 1
    note = db.added[0]
    assert isinstance(note, Message)
    assert note.sender.value == "SYSTEM"
    assert note.body == _NOTE_BODY
    assert db.commits == 1
    events.conversation_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeat_unreachable_failures_do_not_stack_notes():
    db = _FakeDb(existing_notes=1)
    conv = _conv()
    events = SimpleNamespace(conversation_updated=AsyncMock())

    await apply_user_unreachable_side_effects(db, conv, events)

    assert conv.followup_opted_out is True
    assert db.added == []
    assert db.commits == 1


@pytest.mark.asyncio
async def test_first_messenger_unreachable_failure_stamps_opt_out_and_note():
    """Messenger code=551 gets the same once-only stamp, with its own wording."""
    db = _FakeDb(existing_notes=0)
    conv = _conv(channel="facebook_messenger")
    events = SimpleNamespace(conversation_updated=AsyncMock())

    await apply_user_unreachable_side_effects(db, conv, events)

    assert conv.followup_opted_out is True
    assert len(db.added) == 1
    note = db.added[0]
    assert isinstance(note, Message)
    assert note.sender.value == "SYSTEM"
    assert note.body == _MESSENGER_NOTE_BODY
    assert note.body != _NOTE_BODY
    assert db.commits == 1
    events.conversation_updated.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeat_messenger_unreachable_failures_do_not_stack_notes():
    db = _FakeDb(existing_notes=1)
    conv = _conv(channel="facebook_messenger")
    events = SimpleNamespace(conversation_updated=AsyncMock())

    await apply_user_unreachable_side_effects(db, conv, events)

    assert conv.followup_opted_out is True
    assert db.added == []
    assert db.commits == 1


@pytest.mark.asyncio
async def test_channels_without_a_producer_are_left_untouched():
    """Channels with no ``user_unreachable`` sender must stay untouched."""
    db = _FakeDb()
    conv = _conv(channel="zalo_bot")
    events = SimpleNamespace(conversation_updated=AsyncMock())

    await apply_user_unreachable_side_effects(db, conv, events)

    assert conv.followup_opted_out is False
    assert db.added == []
    assert db.commits == 0
    events.conversation_updated.assert_not_awaited()


@pytest.mark.asyncio
async def test_side_effect_failure_never_propagates():
    db = _FakeDb()
    db.scalar = AsyncMock(side_effect=RuntimeError("db boom"))
    conv = _conv()
    events = SimpleNamespace(conversation_updated=AsyncMock())

    await apply_user_unreachable_side_effects(db, conv, events)

    events.conversation_updated.assert_not_awaited()


def test_error_class_constant_is_the_shared_marker():
    """The constant the finalizers compare against must not drift."""
    assert USER_UNREACHABLE_SEND_CLASS == "user_unreachable"
