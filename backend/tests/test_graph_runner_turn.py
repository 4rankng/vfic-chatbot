"""Characterization tests for graph/runner.run_turn — the bot-turn pipeline.

``run_turn`` is the reactive brain: agent -> safety -> ownership guard -> send.
Its outcome matrix (sent / suppressed / error / send_failed) is exactly what a
graph-layer refactor (e.g. breaking the graph<->services cycle) must preserve.

We isolate the control flow by faking the two coupling points:

* ``_agent_turn`` (which otherwise calls the DB-hitting ``build_system_prompt``
  and ``LeadRepository``) is replaced with a canned reply / exception, and
* the injected ``ConversationPort`` (``deps.conversation``) is a stub exposing
  only the handful of methods the pipeline calls.

No DB / Redis / LLM. These pin *current* behavior; one assertion documents a
surprising-but-intentional-to-pin outcome mapping in the agent-error branch.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.graph import runner
from app.graph.llm_semaphore import LLMThrottled
from app.graph.prompts import ERROR_REPLY
from app.graph.runner import run_turn
from app.graph.types import BotRunState, GraphDeps

CONV_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeConv:
    def __init__(self, zalo_chat_id: str = "z1", version: int = 1) -> None:
        self.zalo_chat_id = zalo_chat_id
        self.version = version


class _FakeDB:
    async def refresh(self, conv) -> None:
        return None


class _SendResult:
    def __init__(self, ok: bool = True, error: str | None = None,
                 msg_id: str = "mid-1") -> None:
        self.ok = ok
        self.error = error
        self.msg_id = msg_id


class _FakeZalo:
    def __init__(self, results: list | None = None) -> None:
        self._results = results or [_SendResult()]
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, chat_id: str, text: str) -> _SendResult:
        self.sent.append((chat_id, text))
        return self._results.pop(0) if self._results else _SendResult()

    async def send_chat_action(self, chat_id: str, action: str) -> None:
        return None

    def for_conversation(self, conv):
        return self


class _FakeSafety:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    async def safety(self, candidate: str) -> str:
        return self._raw


def _stub_svc(*, conv=None, owned: bool = True):
    """Build a stub ConversationPort; return ``(svc, recorded_outcomes)``."""
    recorded: list[dict] = []

    class _Svc:
        async def get(self, _id):
            return conv

        async def last_messages(self, c, limit):
            return []

        async def record_bot_pending(self, c):
            return SimpleNamespace(id=777)

        async def recheck_ownership(self, c, version_at_start):
            return owned

        async def record_bot_outcome(self, c, **kw):
            recorded.append(kw)

    return _Svc(), recorded


def _stub_agent(monkeypatch, *replies) -> None:
    """Replace ``_agent_turn`` with a sequence of canned replies / exceptions."""
    seq = list(replies)

    async def _fake(state, deps, user_text, *, chat_id, recent_messages):
        r = seq.pop(0) if seq else ""
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(runner, "_agent_turn", _fake)


def _deps(zalo, *, conversation, safety=object(), persist=None) -> GraphDeps:
    return GraphDeps(
        db=_FakeDB(), agent=object(), safety=safety,
        embedder=object(), zalo=zalo, conversation=conversation, persist=persist,
    )


def _state() -> BotRunState:
    return BotRunState(
        conversation_id=CONV_ID, version_at_start=1, user_text="hi"
    )


# ---------------------------------------------------------------------------
# Outcome matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_conversation_returns_error_without_sending(monkeypatch):
    svc, _ = _stub_svc(conv=None)
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert res == {"outcome": "error", "reason": "conversation_not_found"}
    assert zalo.sent == []  # never touched a missing conversation


@pytest.mark.asyncio
async def test_clean_reply_owned_is_sent_and_persisted(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    persisted: list[dict] = []
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc, persist=persisted.append))

    assert res["outcome"] == "sent"
    assert res["reply"] == "Chào bạn!"
    assert zalo.sent == [("z1", "Chào bạn!")]
    assert persisted == [
        {"chat_id": "z1", "user_text": "hi", "bot_output": "Chào bạn!"}
    ]


@pytest.mark.asyncio
async def test_ownership_lost_during_generation_suppresses_send(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=False)
    _stub_agent(monkeypatch, "Chào bạn!")
    persisted: list[dict] = []
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc, persist=persisted.append))

    assert res["outcome"] == "suppressed"
    assert zalo.sent == []          # takeover during generation -> do not send
    assert persisted == []          # extraction only runs after a real send


@pytest.mark.asyncio
async def test_zalo_send_failure_is_reported_as_send_failed(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    zalo = _FakeZalo(results=[_SendResult(ok=False, error="zalo_rate_limited")])

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert res["outcome"] == "send_failed"
    assert res["reason"] == "zalo_rate_limited"
    assert res["reply"] == "Chào bạn!"


@pytest.mark.asyncio
async def test_agent_exception_falls_back_to_error_reply(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, ValueError("agent blew up"))
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    # The graceful-fallback reply is always ERROR_REPLY...
    assert res["reply"] == ERROR_REPLY
    assert zalo.sent and zalo.sent[0][1] == ERROR_REPLY
    # ...and current behavior labels a *successfully delivered* fallback as
    # outcome "error" (the pipeline distinguishes only send_failed separately).
    # Pinned here so a refactor does not silently change the mapping.
    assert res["outcome"] == "error"


@pytest.mark.asyncio
async def test_llm_throttle_propagates_uncaught(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, LLMThrottled())

    with pytest.raises(LLMThrottled):
        await run_turn(_state(), _deps(_FakeZalo(), conversation=svc))


@pytest.mark.asyncio
async def test_safety_verdict_safe_overrides_with_final_answer(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    # reply contains code -> fast filter flags it for the LLM safety gate
    _stub_agent(monkeypatch, "viết code python ```print('x')```")
    verdict = (
        '{"safe_to_send": true, "final_answer": '
        '"Tôi chỉ tư vấn việc làm, không viết code được."}'
    )
    zalo = _FakeZalo()

    res = await run_turn(
        _state(), _deps(zalo, conversation=svc, safety=_FakeSafety(verdict)),
    )

    assert res["outcome"] == "sent"
    # the safety gate's final_answer replaces the raw agent output
    assert res["reply"] == "Tôi chỉ tư vấn việc làm, không viết code được."
    assert zalo.sent[0][1] == res["reply"]
