from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from app.models.conversation import ConversationMode, MessageSender
from app.services.conversation.state import ConversationState


class _Result:
    def __init__(self, rowcount: int, scalar: int = 5) -> None:
        self.rowcount = rowcount
        self.scalar = scalar

    def scalar_one_or_none(self) -> int | None:
        return self.scalar if self.rowcount == 1 else None


def _conversation(*, mode: ConversationMode, needs_human: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        mode=mode,
        needs_human=needs_human,
        version=3,
        conversation_seq=4,
    )


@pytest.mark.asyncio
async def test_abuse_transition_persists_inbound_and_one_human_escalation(monkeypatch):
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=_Result(1))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    events = MagicMock()
    emitted: list[str] = []
    events.message_created = AsyncMock(
        side_effect=lambda msg, _conv: emitted.append(msg.sender.value)
    )
    events.conversation_updated = AsyncMock(side_effect=lambda _conv: emitted.append("updated"))
    audit = AsyncMock()
    monkeypatch.setattr("app.services.conversation.state.record_audit", audit)
    conv = _conversation(mode=ConversationMode.BOT, needs_human=False)

    transitioned = await ConversationState(
        db, MagicMock(), events
    ).record_inbound_and_escalate_abuse(
        conv,
        body="Tôi đang kiểm tra bot",
        zalo_message_id="msg-1",
        reason="explicit_bot_testing",
    )

    assert transitioned is True
    added_messages = [call.args[0] for call in db.add.call_args_list]
    assert [message.sender for message in added_messages] == [
        MessageSender.WORKER,
        MessageSender.SYSTEM,
    ]
    assert "Tôi đang kiểm tra bot" not in added_messages[1].body
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["payload"]["reason"] == "explicit_bot_testing"
    assert audit.await_args.kwargs["payload"]["version"] == 5
    db.commit.assert_awaited_once()
    assert emitted == ["WORKER", "SYSTEM", "updated"]


@pytest.mark.asyncio
async def test_abuse_transition_is_idempotent_only_for_human_needs_human_pair(monkeypatch):
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=[_Result(0), _Result(1)])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    events = MagicMock()
    events.message_created = AsyncMock()
    events.conversation_updated = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr("app.services.conversation.state.record_audit", audit)
    conv = _conversation(mode=ConversationMode.HUMAN, needs_human=True)

    transitioned = await ConversationState(
        db, MagicMock(), events
    ).record_inbound_and_escalate_abuse(
        conv,
        body="Tôi vẫn đang kiểm tra bot",
        zalo_message_id="msg-2",
        reason="explicit_bot_testing",
    )

    assert transitioned is False
    added_messages = [call.args[0] for call in db.add.call_args_list]
    assert [message.sender for message in added_messages] == [MessageSender.WORKER]
    audit.assert_not_awaited()
    db.commit.assert_awaited_once()
    events.message_created.assert_awaited_once()
    events.conversation_updated.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "needs_human"),
    [
        (ConversationMode.BOT, True),
        (ConversationMode.HUMAN, False),
    ],
)
async def test_partial_state_still_requires_abuse_escalation(monkeypatch, mode, needs_human):
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=_Result(1))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    events = MagicMock(message_created=AsyncMock(), conversation_updated=AsyncMock())
    monkeypatch.setattr("app.services.conversation.state.record_audit", AsyncMock())

    transitioned = await ConversationState(
        db, MagicMock(), events
    ).record_inbound_and_escalate_abuse(
        _conversation(mode=mode, needs_human=needs_human),
        body="Tôi không phải ứng viên",
        reason="explicit_non_candidate",
    )

    assert transitioned is True
    assert db.execute.await_count == 1
