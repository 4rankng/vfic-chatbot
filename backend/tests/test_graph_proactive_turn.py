"""Characterization tests for graph/proactive.run_proactive_turn — the proactive nudge pipeline.

``run_proactive_turn`` is the proactive brain: guards -> single LLM JSON decision ->
safety -> send -> persist. Its outcome matrix (sent / suppressed / send_failed) is
what a graph-layer refactor (e.g. porting the conversation service) must preserve.

We isolate control flow by faking the coupling points: the ConversationService
constructed inside the turn, the agent LLM, the Zalo sender, and the two lazy
DB-hitting helpers (build_system_prompt, conversation_allowed_by_followup_rules).
No DB / Redis / LLM.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.graph.proactive import run_proactive_turn

CONV_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeDB:
    async def refresh(self, conv) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class _FakeConv:
    """A conversation that passes every proactive guard by default."""

    def __init__(self, **overrides) -> None:
        self.id = CONV_ID
        self.zalo_chat_id = "z1"
        self.version = 1
        self.mode = "BOT"
        self.status = "OPEN"
        self.followup_opted_out = False
        self.followup_count = 0
        self.bot_locked_until = None
        self.last_inbound_at = datetime.now(timezone.utc) - timedelta(hours=1)
        self.last_followup_at = None
        self.last_followup_attempt_at = None
        for key, value in overrides.items():
            setattr(self, key, value)


class _SendResult:
    def __init__(
        self,
        ok: bool = True,
        msg_id: str = "mid-1",
        error: str | None = None,
        error_class: str | None = None,
    ) -> None:
        self.ok = ok
        self.msg_id = msg_id
        self.error = error
        self.error_class = error_class


class _FakeZalo:
    def __init__(self, *, send_raises: bool = False, result: _SendResult | None = None) -> None:
        self._send_raises = send_raises
        self._result = result or _SendResult()
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, chat_id: str, text: str) -> _SendResult:
        if self._send_raises:
            raise RuntimeError("zalo boom")
        self.sent.append((chat_id, text))
        return self._result

    def for_conversation(self, conv):
        return self


class _FakeAgent:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    async def agent(
        self,
        text,
        *,
        system,
        retrieval,
        embedder,
        retry_empty_generation=False,
    ) -> str:
        return self._raw


def _stub_svc(*, acquired: bool = True, owned: bool = True):
    """Build a stub ConversationPort; return ``(svc, recorded_proactive_outcomes)``."""
    recorded: list[dict] = []

    class _State:
        async def record_proactive_outcome(self, conv, *, message, result, lock_owner=None):
            recorded.append({"message": message, "ok": result.ok})
            return object()

        async def release_lock(self, conv, lock_owner=None) -> None:
            return None

    class _Svc:
        def __init__(self) -> None:
            self.state = _State()

        async def acquire_lock(self, conv_id, ttl_seconds=None):
            return acquired

        async def last_messages(self, conv, *, limit):
            return []

        async def recheck_ownership(self, conv, version_at_start, lock_owner=None):
            return owned

    return _Svc(), recorded


def _patch_lazy_helpers(monkeypatch) -> None:
    """Neutralize the lazy DB-hitting system-prompt build inside the turn."""

    async def _system_prompt(db, *, provider=None):  # noqa: ARG001
        return "", True

    monkeypatch.setattr("app.graph.context.build_system_prompt", _system_prompt)


class _NoLead:
    async def profile_text(self, chat_id: str) -> str:
        return ""


async def _always_allowed(conv):
    return True, ""


def _deps(agent, zalo, *, conversation, proactive_state=None) -> "object":
    from app.graph.safety import DeterministicReplyPolicy
    from app.graph.types import GraphDeps

    deps = GraphDeps(
        db=_FakeDB(),
        agent=agent,
        safety=object(),
        embedder=object(),
        zalo=zalo,
        conversation=conversation,
        retrieval=object(),
        reply_policy=DeterministicReplyPolicy(),
        lead=_NoLead(),
        followup_allowed=_always_allowed,
    )
    deps.proactive_state = proactive_state
    return deps


# ---------------------------------------------------------------------------
# Outcome matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_recruitment_policy_suppresses_proactive_outreach(monkeypatch):
    svc, _ = _stub_svc()
    _patch_lazy_helpers(monkeypatch)
    agent = _FakeAgent('{"send": true, "message": "never", "reason": "x"}')
    zalo = _FakeZalo()
    deps = _deps(agent, zalo, conversation=svc)

    async def _unsupported_policy():
        return SimpleNamespace(pack_key="unsupported-pack")

    deps.runtime_policy = SimpleNamespace(resolve_active_policy=_unsupported_policy)

    result = await run_proactive_turn(_FakeConv(), deps)

    assert result == {
        "outcome": "proactive:suppressed",
        "reason": "proactive_not_enabled",
        "reply": "",
    }
    assert zalo.sent == []


@pytest.mark.asyncio
async def test_mode_not_bot_suppresses_without_agent_call(monkeypatch):
    svc, _ = _stub_svc()
    _patch_lazy_helpers(monkeypatch)
    agent = _FakeAgent('{"send": true, "message": "never", "reason": "x"}')
    zalo = _FakeZalo()
    conv = _FakeConv(mode="HUMAN")

    res = await run_proactive_turn(conv, _deps(agent, zalo, conversation=svc))

    assert res["outcome"] == "proactive:suppressed"
    assert res["reason"] == "mode/status"
    assert zalo.sent == []  # suppressed before any send


@pytest.mark.asyncio
async def test_silence_opt_out_uses_injected_recruitment_state(monkeypatch):
    svc, _ = _stub_svc()
    _patch_lazy_helpers(monkeypatch)
    agent = _FakeAgent('{"send": true, "message": "never", "reason": "x"}')
    zalo = _FakeZalo()
    conv = _FakeConv(
        followup_count=2,
        last_followup_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    class _ProactiveState:
        opted_out = False

        async def refresh(self, _conversation):
            return None

        async def has_worker_reply_since(self, _conversation_id, _since):
            return False

        async def opt_out_for_silence(self, conversation):
            conversation.followup_opted_out = True
            self.opted_out = True

    state = _ProactiveState()
    result = await run_proactive_turn(
        conv,
        _deps(agent, zalo, conversation=svc, proactive_state=state),
    )

    assert result["outcome"] == "proactive:suppressed"
    assert result["reason"] == "silence_optout"
    assert state.opted_out is True
    assert zalo.sent == []


@pytest.mark.asyncio
async def test_agent_decides_not_to_send_suppresses(monkeypatch):
    svc, recorded = _stub_svc()
    _patch_lazy_helpers(monkeypatch)
    agent = _FakeAgent('{"send": false, "message": "", "reason": "not_interested"}')
    zalo = _FakeZalo()
    conv = _FakeConv()

    res = await run_proactive_turn(conv, _deps(agent, zalo, conversation=svc))

    assert res["outcome"] == "proactive:suppressed"
    assert res["reason"] == "not_interested"
    assert zalo.sent == []
    # The agent-decided-not-to-send path records a failed (non-send) outcome.
    assert recorded == [{"message": "", "ok": False}]


@pytest.mark.asyncio
async def test_clean_decision_is_sent(monkeypatch):
    svc, recorded = _stub_svc()
    _patch_lazy_helpers(monkeypatch)
    agent = _FakeAgent('{"send": true, "message": "Mình hỗ trợ thêm nhé?", "reason": "warm"}')
    zalo = _FakeZalo()
    conv = _FakeConv()

    res = await run_proactive_turn(conv, _deps(agent, zalo, conversation=svc))

    assert res["outcome"] == "sent"
    assert res["reply"] == "Mình hỗ trợ thêm nhé?"
    assert zalo.sent == [("z1", "Mình hỗ trợ thêm nhé?")]
    assert recorded == [{"message": "Mình hỗ trợ thêm nhé?", "ok": True}]


@pytest.mark.asyncio
async def test_clean_decision_persists_then_dispatches_without_direct_send(monkeypatch):
    svc, recorded = _stub_svc()
    _patch_lazy_helpers(monkeypatch)
    agent = _FakeAgent('{"send": true, "message": "Mình hỗ trợ thêm nhé?", "reason": "warm"}')
    zalo = _FakeZalo()
    conv = _FakeConv()
    prepared: list[dict] = []

    async def prepare_proactive_message(conv, *, body, channel, payload):
        prepared.append({"body": body, "channel": channel, "payload": payload})
        return type("Pending", (), {"id": 99})()

    async def dispatch_outbound_message(*, message_id):
        assert message_id == 99
        return _SendResult()

    async def record_durable(conv, *, message, result, lock_owner=None, **kwargs):
        recorded.append({"message": message, "ok": result.ok, **kwargs})

    svc.prepare_proactive_message = prepare_proactive_message
    svc.dispatch_outbound_message = dispatch_outbound_message
    svc.state.record_proactive_outcome = record_durable

    res = await run_proactive_turn(conv, _deps(agent, zalo, conversation=svc))

    assert res["outcome"] == "sent"
    assert zalo.sent == []
    assert prepared == [
        {
            "body": "Mình hỗ trợ thêm nhé?",
            "channel": "zalo_bot",
            "payload": {"chat_id": "z1", "text": "Mình hỗ trợ thêm nhé?"},
        }
    ]
    assert recorded[0]["pending_message_id"] == 99


@pytest.mark.asyncio
async def test_send_exception_is_reported_as_send_failed(monkeypatch):
    svc, recorded = _stub_svc()
    _patch_lazy_helpers(monkeypatch)
    agent = _FakeAgent('{"send": true, "message": "Theo dõi lại nhé?", "reason": "warm"}')
    zalo = _FakeZalo(send_raises=True)
    conv = _FakeConv()

    res = await run_proactive_turn(conv, _deps(agent, zalo, conversation=svc))

    assert res["outcome"] == "send_failed"
    assert res["reply"]  # retry_exhausted_fallback or the candidate
    assert recorded == [{"message": res["reply"], "ok": False}]
