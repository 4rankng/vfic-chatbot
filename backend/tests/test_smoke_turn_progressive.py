"""Behaviour of the pre-flip smoke gate's progressive-send probes.

The gate is the one end-to-end check that runs against the real
``ConversationService`` before a blue-green flip, so these tests drive the real
probe runners and the real persisted-state assertions over seeded rows: a probe
must pass on a healthy progressive turn and fail on every way the delivery can
reach a candidate broken -- a blanked early bubble, an unpersisted remainder, or
an outbound command left in flight.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.conversation_messaging.domain.statuses import DeliveryStatus, MessageSender
from app.models.conversation import Message
from app.models.outbox import OutboxStatus, OutboundOutbox
from scripts import smoke_turn

_STREAMED = smoke_turn.SMOKE_STREAM_REPLY
# Any split of the streamed answer satisfies the contract under test: the
# bubble carries a non-blank prefix, the remainder the rest, and together they
# carry the answer exactly once. Where the sender really cuts is the runner's
# business, not the gate's.
_SPLIT = len(_STREAMED) // 2
_BUBBLE_BODY = _STREAMED[:_SPLIT]
_REMAINDER_BODY = _STREAMED[_SPLIT:]


def _bot_message(
    message_id: int,
    body: str,
    *,
    status: DeliveryStatus = DeliveryStatus.SENT,
    provider_id: str | None = None,
    external_error: str | None = None,
) -> Message:
    message = Message(
        conversation_id=uuid.uuid4(),
        sender=MessageSender.BOT,
        body=body,
        delivery_status=status,
        provider_message_id=provider_id,
        zalo_message_id=provider_id,
        external_error=external_error,
    )
    message.id = message_id
    return message


def _outbox(
    message_id: int,
    *,
    status: str = OutboxStatus.SENT.value,
    provider_id: str | None = None,
) -> OutboundOutbox:
    row = OutboundOutbox(
        message_id=message_id,
        channel="zalo_bot",
        payload={"chat_id": "zalo-smoke", "text": "smoke"},
        status=status,
        zalo_message_id=provider_id,
        provider_message_id=provider_id,
    )
    row.id = 1000 + message_id
    return row


class _FakeScalarResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _FakeSession:
    """Answers only the reads the probe's assertions make, from seeded rows."""

    def __init__(
        self, messages: list[Message] | None = None, outboxes: list[OutboundOutbox] | None = None
    ):
        self._messages = messages or []
        self._outboxes = outboxes or []

    async def scalars(self, statement) -> _FakeScalarResult:
        entity = statement.column_descriptions[0]["entity"]
        if entity is Message:
            return _FakeScalarResult(self._messages)
        if entity is OutboundOutbox:
            # The gate asks for ONE message's command, so filter on the id the
            # statement binds: a query must not see a neighbour's row.
            wanted = {
                value
                for value in statement.compile().params.values()
                if isinstance(value, int) and not isinstance(value, bool)
            }
            return _FakeScalarResult([row for row in self._outboxes if row.message_id in wanted])
        raise AssertionError(f"unexpected entity in the smoke probe query: {entity!r}")

    async def scalar(self, _statement) -> int | None:
        return None

    async def execute(self, _statement) -> object:
        return object()

    async def commit(self) -> None:
        return None


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeEngine:
    async def dispose(self) -> None:
        return None


def _patch_probe_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcome: dict,
    pending_message_id: int,
    messages: list[Message],
    outboxes: list[OutboundOutbox],
) -> None:
    """Stub the database, the seed and the turn; leave the probes themselves real."""
    sessions = [
        _FakeSessionContext(_FakeSession()),
        _FakeSessionContext(_FakeSession(messages, outboxes)),
        _FakeSessionContext(_FakeSession()),
    ]

    def _session_factory():
        if not sessions:
            raise AssertionError("unexpected session_factory() call")
        return sessions.pop(0)

    monkeypatch.setattr(
        smoke_turn,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://smoke"),
    )
    monkeypatch.setattr(smoke_turn, "create_async_engine", lambda *_args, **_kwargs: _FakeEngine())
    monkeypatch.setattr(
        smoke_turn, "async_sessionmaker", lambda *_args, **_kwargs: _session_factory
    )
    monkeypatch.setattr(smoke_turn.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(
        smoke_turn,
        "_seed_smoke_conversation",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=uuid.uuid4(), version=7),
                SimpleNamespace(id=uuid.uuid4()),
                SimpleNamespace(id=uuid.uuid4()),
                uuid.uuid4(),
            )
        ),
    )
    monkeypatch.setattr(smoke_turn, "_cleanup", AsyncMock(return_value=None))

    async def _fake_run_turn(state, _deps):
        state.pending_message_id = pending_message_id
        return outcome

    monkeypatch.setattr(smoke_turn, "run_turn", AsyncMock(side_effect=_fake_run_turn))


def _healthy_pair() -> tuple[list[Message], list[OutboundOutbox]]:
    bubble = _bot_message(11, _BUBBLE_BODY, provider_id="smoke-11")
    remainder = _bot_message(12, _REMAINDER_BODY, provider_id="smoke-12")
    return [bubble, remainder], [
        _outbox(11, provider_id="smoke-11"),
        _outbox(12, provider_id="smoke-12"),
    ]


@pytest.mark.asyncio
async def test_progressive_probe_passes_when_both_halves_are_terminal(
    monkeypatch: pytest.MonkeyPatch,
):
    messages, outboxes = _healthy_pair()
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "sent", "reply": _REMAINDER_BODY},
        pending_message_id=12,
        messages=messages,
        outboxes=outboxes,
    )

    assert await smoke_turn._run_progressive_smoke(inject_failure=False) == 0


@pytest.mark.asyncio
async def test_progressive_probe_fails_when_the_early_bubble_was_blanked(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """REL-13's signature: a delivered bubble overwritten with "nothing was sent"."""
    messages, outboxes = _healthy_pair()
    messages[0].body = ""
    messages[0].delivery_status = DeliveryStatus.SUPPRESSED
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "sent", "reply": _REMAINDER_BODY},
        pending_message_id=12,
        messages=messages,
        outboxes=outboxes,
    )

    assert await smoke_turn._run_progressive_smoke(inject_failure=False) == 1
    assert "progressive early bubble" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_progressive_probe_fails_when_the_remainder_never_persisted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    messages, outboxes = _healthy_pair()
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "sent", "reply": _REMAINDER_BODY},
        pending_message_id=12,
        messages=messages[:1],
        outboxes=outboxes[:1],
    )

    assert await smoke_turn._run_progressive_smoke(inject_failure=False) == 1
    assert "expected exactly two BOT messages" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_progressive_probe_fails_when_the_bubble_command_stayed_in_flight(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A bubble the candidate read must not leave its outbox row in SENDING."""
    messages, outboxes = _healthy_pair()
    outboxes[0].status = OutboxStatus.SENDING.value
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "sent", "reply": _REMAINDER_BODY},
        pending_message_id=12,
        messages=messages,
        outboxes=outboxes,
    )

    assert await smoke_turn._run_progressive_smoke(inject_failure=False) == 1
    assert "progressive early bubble outbound_outbox status" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_progressive_probe_fails_when_the_split_sent_text_twice(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    messages, outboxes = _healthy_pair()
    messages[1].body = _STREAMED
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "sent", "reply": _STREAMED},
        pending_message_id=12,
        messages=messages,
        outboxes=outboxes,
    )

    assert await smoke_turn._run_progressive_smoke(inject_failure=False) == 1
    assert "did not carry the streamed answer exactly once" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_failure_probe_passes_while_the_delivered_bubble_survives(
    monkeypatch: pytest.MonkeyPatch,
):
    bubble = _bot_message(21, _BUBBLE_BODY, provider_id="smoke-21")
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "error", "reply": _BUBBLE_BODY},
        pending_message_id=21,
        messages=[bubble],
        outboxes=[_outbox(21, provider_id="smoke-21")],
    )

    assert await smoke_turn._run_progressive_failure_smoke(inject_failure=False) == 0


@pytest.mark.asyncio
async def test_failure_probe_fails_when_the_lane_failure_blanked_the_bubble(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    bubble = _bot_message(21, "", status=DeliveryStatus.SUPPRESSED)
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "error", "reply": ""},
        pending_message_id=21,
        messages=[bubble],
        outboxes=[_outbox(21, status=OutboxStatus.SENDING.value)],
    )

    assert await smoke_turn._run_progressive_failure_smoke(inject_failure=False) == 1
    assert "delivered early bubble" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_failure_probe_fails_when_the_delivered_bubble_lost_its_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    bubble = _bot_message(21, _BUBBLE_BODY)
    _patch_probe_runtime(
        monkeypatch,
        outcome={"outcome": "error", "reply": _BUBBLE_BODY},
        pending_message_id=21,
        messages=[bubble],
        outboxes=[_outbox(21, provider_id="smoke-21")],
    )

    assert await smoke_turn._run_progressive_failure_smoke(inject_failure=False) == 1
    assert "missing provider message id" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_streaming_stub_streams_through_on_delta_and_returns_the_same_text():
    seen: list[str] = []

    async def _on_delta(text: str) -> None:
        seen.append(text)

    reply = await smoke_turn._StubStreamingAgent().agent("smoke probe", on_delta=_on_delta)

    assert "".join(seen) == reply == _STREAMED
    assert len(seen) > 1, "the answer must arrive in pieces, not one blocking reply"


@pytest.mark.asyncio
async def test_failing_stub_waits_for_the_wire_before_it_kills_the_lane():
    wire_ack = asyncio.Event()
    agent = smoke_turn._StubFailingStreamingAgent(wire_ack)
    seen: list[str] = []

    async def _on_delta(text: str) -> None:
        seen.append(text)

    lane = asyncio.create_task(agent.agent("smoke probe", on_delta=_on_delta))
    await asyncio.sleep(0)
    assert not lane.done(), "the lane must not fail before the bubble reached the candidate"
    assert "".join(seen) == _STREAMED

    wire_ack.set()
    with pytest.raises(RuntimeError):
        await lane
