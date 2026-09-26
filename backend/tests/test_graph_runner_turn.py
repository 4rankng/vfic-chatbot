"""Characterization tests for graph/runner.run_turn — the bot-turn pipeline.

``run_turn`` is the reactive brain: agent -> ownership guard -> send.
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

import asyncio
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.graph import runner
from app.graph.direct_context import DirectContext, ProjectTurnContext
from app.graph.llm_semaphore import LLMThrottled
from app.graph.ports import TurnDecisions
from app.graph.runner import run_turn
from app.graph.types import BotRunState, GraphDeps

# These tests observe scheduling directly, not wall-clock budgets; the timeout
# only guards against an event-loop hang.
pytestmark = pytest.mark.timeout(30)

CONV_ID = "00000000-0000-0000-0000-000000000001"


def test_vacancy_evidence_query_prefers_durable_project_focus_over_free_text_history():
    from app.graph.ports import TurnDecisions

    history = [SimpleNamespace(sender="WORKER", body="LG Tràng Duệ đang tuyển không?")]

    # The Jev recent_vacancy flag marks the thread; the latest candidate body
    # supplies the context (what the keyword scan used to stitch in).
    assert (
        runner._vacancy_evidence_query(
            "lương bao nhiêu?",
            TurnDecisions(intent="faq_detail", recent_vacancy=True),
            history)
        == "LG Tràng Duệ đang tuyển không?\nlương bao nhiêu?"
    )
    assert (
        runner._vacancy_evidence_query(
            "giờ làm của LG",
            TurnDecisions(intent="faq_detail", recent_vacancy=True),
            history)
        == "LG Tràng Duệ đang tuyển không?\ngiờ làm của LG"
    )
    assert (
        runner._vacancy_evidence_query(
            "lương bao nhiêu?",
            TurnDecisions(intent="faq_detail"),
            focused_project=True)
        == "lương bao nhiêu?"
    )
    assert (
        runner._vacancy_evidence_query(
            "bên mình còn tuyển không?", TurnDecisions(vacancy_listing=True)
        )
        is None
    )
    # Without a vacancy thread context, a detail question gets no forced evidence.
    assert (
        runner._vacancy_evidence_query("lương bao nhiêu?", TurnDecisions(intent="faq_detail"))
        is None
    )


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeConv:
    def __init__(
        self,
        zalo_chat_id: str | None = "z1",
        version: int = 1,
        zalo_channel: str = "bot",
        channel_identity=None,
        contact_id=None) -> None:
        self.zalo_chat_id = zalo_chat_id
        self.zalo_channel = zalo_channel
        self.channel_identity = channel_identity
        self.contact_id = contact_id
        self.version = version
        self.bot_lock_owner = None
        self.bot_locked_until = None


class _FakeDB:
    """Minimal session stand-in.

    Supports ``rollback`` plus a poison flag so adapter-error tests can mimic a
    SQLAlchemy session left in a needs-rollback state: once ``_poisoned`` is set
    (an adapter's DB call failed), any further ``refresh`` raises until
    ``rollback()`` clears it — mirroring ``PendingRollbackError``.
    """

    def __init__(self) -> None:
        self.rollbacks = 0
        self.refresh_calls: list[tuple | None] = []
        self._poisoned = False

    async def refresh(self, conv, attribute_names=None) -> None:
        if self._poisoned:
            raise RuntimeError("simulated PendingRollbackError: session needs rollback")
        self.refresh_calls.append(tuple(attribute_names) if attribute_names else None)
        return None

    async def rollback(self) -> None:
        self._poisoned = False
        self.rollbacks += 1


class _SendResult:
    def __init__(
        self,
        ok: bool = True,
        error: str | None = None,
        msg_id: str = "mid-1",
        error_class: str | None = None,
        telemetry=None) -> None:
        self.ok = ok
        self.error = error
        self.msg_id = msg_id
        self.error_class = error_class
        self.telemetry = telemetry


class _FakeZalo:
    def __init__(self, results: list | None = None) -> None:
        self._results = results or [_SendResult()]
        self.sent: list[tuple[str, str]] = []
        self.actions: list[str] = []

    async def send_message(self, chat_id: str, text: str) -> _SendResult:
        self.sent.append((chat_id, text))
        return self._results.pop(0) if self._results else _SendResult()

    async def send_chat_action(self, chat_id: str, action: str) -> None:
        self.actions.append(action)
        return None

    def for_conversation(self, conv):
        return self


class _DispatchResult:
    """Mirrors ``app.services.outbox.repository.DispatchResult`` for the fakes."""

    def __init__(
        self,
        *,
        outbox_id: int,
        message_id: int,
        ok: bool = True,
        provider_message_id: str | None = "mid-1",
        error: str | None = None,
        error_class: str | None = None,
        suppressed: bool = False,
        telemetry=None) -> None:
        self.outbox_id = outbox_id
        self.message_id = message_id
        self.ok = ok
        self.provider_message_id = provider_message_id
        self.error = error
        self.error_class = error_class
        self.suppressed = suppressed
        self.telemetry = telemetry

    @property
    def msg_id(self) -> str | None:
        return self.provider_message_id


def _stub_svc(*, conv=None, owned: bool = True, messages: list | None = None, durable=False):
    """Build a stub ConversationPort; return ``(svc, recorded_outcomes)``.

    ``durable=True`` adds the durable outbox seam
    (``dispatch_outbound_message`` + ``finalize_outbound_dispatch``) that the
    progressive-send path requires, so the claim→dispatch→finalize chain can be
    observed without a database. ``record_bot_pending`` hands out distinct ids so
    a second placeholder (the progressive remainder) is a different row.
    """
    recorded: list[dict] = []

    class _Svc:
        def __init__(self) -> None:
            self.claims: list[dict] = []
            self.dispatched: list[dict] = []
            self.finalized: list[dict] = []
            self.pending_bodies: list[str] = []
            self.agent_returned_after_dispatches: list[int] = []
            self.early_dispatched = asyncio.Event()
            self.claim_attempted = asyncio.Event()
            self._next_pending_id = 777

        async def get(self, _id):
            return conv

        async def last_messages(self, c, limit):
            return messages or []

        async def record_bot_pending(self, c, **kwargs):
            self._next_pending_id += 1
            self.pending_bodies.append(kwargs.get("body", ""))
            return SimpleNamespace(id=self._next_pending_id - 1)

        async def recheck_ownership(self, c, version_at_start, lock_owner=None):
            return owned

        async def claim_send(
            self, c, *, version_at_start, lock_owner, pending_message_id, reply, **kwargs
        ):
            # The fake models the send gate, not the SENDING row: the claim succeeds
            # iff ownership holds AND there is a pending row to flip (mirrors the real
            # atomic claim's preconditions + ownership guard).
            claimed = owned and pending_message_id is not None
            self.claim_attempted.set()
            self.claims.append(
                {
                    "pending_message_id": pending_message_id,
                    "reply": reply,
                    "outbox_channel": kwargs.get("outbox_channel"),
                    "outbox_payload": kwargs.get("outbox_payload"),
                    "claimed": claimed,
                }
            )
            return claimed

        async def record_bot_outcome(self, c, **kw):
            recorded.append(kw)

    class _DurableSvc(_Svc):
        """Adds the durable outbox seam progressive send requires."""

        async def dispatch_outbound_message(self, *, message_id):
            text = next(
                (
                    claim["outbox_payload"]["text"]
                    for claim in self.claims
                    if claim["pending_message_id"] == message_id
                    and claim["outbox_payload"] is not None
                ),
                None,
            )
            self.dispatched.append({"message_id": message_id, "text": text})
            self.early_dispatched.set()
            return _DispatchResult(
                outbox_id=message_id,
                message_id=message_id,
                ok=True,
                provider_message_id=f"prov-{message_id}",
            )

        async def finalize_outbound_dispatch(self, c, **kw):
            self.finalized.append(kw)
            return SimpleNamespace(id=kw.get("message_id"))

    # Without the durable seam ``_dispatch_claimed_message`` falls back to the
    # injected zalo sender, which is what every pre-progressive test expects.
    return (_DurableSvc() if durable else _Svc()), recorded


def _stub_agent(monkeypatch, *replies) -> None:
    """Replace ``_agent_turn`` with a sequence of canned replies / exceptions."""
    seq = list(replies)

    async def _fake(
        state,
        deps,
        user_text,
        *,
        provider=None,
        chat_id,
        recent_messages,
        contact_id=None,
        timings=None,
        decisions=None,
        lead_row=None):  # noqa: ARG001
        r = seq.pop(0) if seq else ""
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(runner, "_agent_turn", _fake)


def _stub_streaming_agent(
    monkeypatch,
    parts,
    *,
    full=None,
    evidence=None,
    svc=None,
    pause_after=None,
    pause_event=None) -> None:
    """Replace ``_agent_turn`` with a streaming fake.

    ``parts`` are pushed through ``on_delta`` in order (the raw stream the
    progressive sender sees). ``evidence`` is published through ``on_evidence``
    before the first delta. ``pause_after`` (a part index) makes the fake block
    until ``pause_event`` fires — that is what proves an early send happened while
    generation was still running. ``full`` overrides the returned text (to model a
    provider that retried mid-stream).
    """
    async def _fake(
        state,
        deps,
        user_text,
        *,
        provider=None,
        chat_id,
        recent_messages,
        contact_id=None,
        timings=None,
        decisions=None,
        lead_row=None,
        on_delta=None,
        on_evidence=None,
        **kwargs):  # noqa: ARG001
        if on_evidence is not None and evidence is not None:
            await on_evidence(list(evidence))
        for index, part in enumerate(parts):
            if on_delta is not None:
                await on_delta(part)
            if pause_after is not None and index == pause_after:
                event = pause_event or (svc.early_dispatched if svc is not None else None)
                assert event is not None, "pause_after needs svc or pause_event"
                await asyncio.wait_for(event.wait(), timeout=5)
            # Give the concurrent early sender every chance to act on the delta
            # before the next one lands (deterministic: no wall-clock wait).
            for _ in range(20):
                await asyncio.sleep(0)
        if svc is not None:
            # Snapshot of how many messages had been dispatched when the agent
            # returned: 1 means the early bubble went out first.
            svc.agent_returned_after_dispatches.append(len(svc.dispatched))
        return full if full is not None else "".join(parts)

    monkeypatch.setattr(runner, "_agent_turn", _fake)


def _deps(
    zalo,
    *,
    conversation,
    persist=None,
    faq_bypass=None,
    enrich_oa_profile=None,
    db=None,
    progressive_send=False) -> GraphDeps:
    from app.conversation_messaging.infrastructure.delivery_status import (
        SqlAlchemyDeliveryStatusValues)

    return GraphDeps(
        db=db if db is not None else _FakeDB(),
        agent=object(),
        embedder=object(),
        zalo=zalo,
        conversation=conversation,
        retrieval=object(),
        persist=persist,
        faq_bypass=faq_bypass,
        enrich_oa_profile=enrich_oa_profile,
        delivery_statuses=SqlAlchemyDeliveryStatusValues(),
        progressive_send=progressive_send)


def _state() -> BotRunState:
    # A factual job query — exercises the agent path (the fast lane only intercepts
    # non-factual greetings/pleasantries).
    return BotRunState(
        conversation_id=CONV_ID, version_at_start=1, user_text="tôi muốn tìm việc lái xe"
    )


def _state_with_user_name(user_name: str) -> BotRunState:
    return BotRunState(
        conversation_id=CONV_ID,
        version_at_start=1,
        user_text="tôi muốn tìm việc lái xe",
        user_name=user_name)


@pytest.mark.asyncio
async def test_messenger_turn_persists_messenger_outbox_route(monkeypatch):
    conv = _FakeConv(
        zalo_chat_id=None,
        zalo_channel="facebook_messenger",
        channel_identity=SimpleNamespace(
            provider="facebook_messenger",
            account_key="page-1",
            external_id="psid-1"))
    svc, recorded = _stub_svc(conv=conv)
    svc.dispatch_outbound_message = AsyncMock(return_value=_SendResult())
    _stub_agent(monkeypatch, "Chào bạn!")

    result = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc))

    assert result["outcome"] == "sent"
    assert recorded[-1]["outbox_channel"] == "facebook_messenger"
    assert recorded[-1]["outbox_payload"] == {
        "chat_id": "psid-1",
        "text": "Chào bạn!",
    }


@pytest.mark.asyncio
async def test_project_detail_turn_uses_direct_context_llm():
    class _DirectReader:
        async def active_context(self):
            return DirectContext(
                knowledge_base_id="kb-1",
                persona_body="Bạn là tư vấn viên.",
                knowledge_text=(
                    "Question: LG Display Hải Phòng tuyển vị trí gì?\n\n"
                    "Answer: LG Display Hải Phòng tuyển công nhân thời vụ làm sản "
                    "xuất tại Khu công nghiệp Tràng Duệ, An Dương, Hải Phòng."
                ))

    class _DirectAgent:
        calls = 0

        async def direct(self, user_text, *, system, metrics=None):
            self.calls += 1
            assert "KIẾN THỨC ĐƯỢC CUNG CẤP TOÀN VĂN" in system
            return "LG Display Hải Phòng tuyển công nhân thời vụ."

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv)
    zalo = _FakeZalo()
    deps = _deps(zalo, conversation=svc)
    direct_agent = _DirectAgent()
    deps.agent = direct_agent
    deps.direct_context = _DirectReader()

    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="Công việc ở LG Display làm gì?"),
        deps)

    assert result["outcome"] == "direct_context"
    assert result["reply"] == "LG Display Hải Phòng tuyển công nhân thời vụ."
    assert direct_agent.calls == 1


@pytest.mark.asyncio
async def test_direct_context_strips_minimax_reasoning_before_delivery():
    class _DirectReader:
        async def active_context(self):
            return DirectContext(
                knowledge_base_id="kb-rorze",
                persona_body="Bạn là tư vấn viên.",
                knowledge_text="Rorze đang tuyển nhân viên lắp ráp và vận hành máy CNC.")

    class _DirectAgent:
        async def direct(self, user_text, *, system, metrics=None):  # noqa: ARG002
            return (
                '<think>\nThe user is asking "co viec o rorze ko".\n</think>\n\n'
                "Có bạn nhé! VFIC đang tuyển 2 vị trí tại Rorze."
            )

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv)
    zalo = _FakeZalo()
    deps = _deps(zalo, conversation=svc)
    deps.agent = _DirectAgent()
    deps.direct_context = _DirectReader()

    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="co viec o rorze ko"),
        deps)

    # The boundary drops the provider thinking block but does not strip the
    # whitespace that followed it — the answer ships as generated.
    visible_reply = "\n\nCó bạn nhé! VFIC đang tuyển 2 vị trí tại Rorze."
    assert result == {"outcome": "direct_context", "reply": visible_reply}
    assert zalo.sent == [("z1", visible_reply)]
    assert recorded[-1]["reply"] == visible_reply


@pytest.mark.asyncio
async def test_direct_context_malformed_think_never_reaches_delivery():
    class _DirectReader:
        async def active_context(self):
            return DirectContext(
                knowledge_base_id="kb-rorze",
                persona_body="Bạn là tư vấn viên.",
                knowledge_text="Rorze đang tuyển nhân viên lắp ráp.")

    class _DirectAgent:
        async def direct(self, user_text, *, system, metrics=None):  # noqa: ARG002
            return "<think\ninternal reasoning from a truncated provider response"

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv)
    zalo = _FakeZalo()
    deps = _deps(zalo, conversation=svc)
    deps.agent = _DirectAgent()
    deps.direct_context = _DirectReader()

    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="Công việc ở Rorze làm gì?"),
        deps)

    # The reply cleaned to nothing (reasoning-only output) → the turn stays
    # silent: nothing sent, SUPPRESSED audit row.
    assert result == {"outcome": "suppressed", "reply": ""}
    assert zalo.sent == []
    assert recorded[-1]["reply"] == ""


@pytest.mark.asyncio
async def test_converged_content_boundary_strips_reasoning_from_curated_lane():
    class _ProjectReader:
        async def resolve(self, conv, user_text):  # noqa: ARG002
            return ProjectTurnContext(
                state="EXPLORE",
                clarification=(
                    "<think>internal routing note</think>"
                    "**Bạn muốn hỏi Rorze hay LG Display?**"
                ))

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv)
    zalo = _FakeZalo()
    deps = _deps(zalo, conversation=svc)
    deps.direct_context = _ProjectReader()

    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="Rorze ở đâu?"),
        deps)

    visible_reply = "**Bạn muốn hỏi Rorze hay LG Display?**"
    assert result == {"outcome": "project_clarification", "reply": visible_reply}
    assert zalo.sent == [("z1", visible_reply)]
    assert recorded[-1]["reply"] == visible_reply


@pytest.mark.asyncio
async def test_generic_vacancy_listing_bypasses_focused_single_page(monkeypatch):
    class _DirectReader:
        calls = 0

        async def active_context(self):
            self.calls += 1
            return DirectContext(
                knowledge_base_id="kb-1",
                persona_body="Bạn là tư vấn viên.",
                knowledge_text=(
                    "Question: LG Display tuyển gì?\n\n"
                    "Answer: LG Display tuyển công nhân thời vụ."
                ))

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv)
    deps = _deps(_FakeZalo(), conversation=svc)
    direct_reader = _DirectReader()
    deps.direct_context = direct_reader
    # Jev decision port stub: this scenario is a generic vacancy listing turn.
    deps.turn_decisions = SimpleNamespace(
        decide_turn=AsyncMock(
            return_value=TurnDecisions(
                intent="recommend", intent_confidence=0.94, vacancy_listing=True
            )
        )
    )
    agent_turn = AsyncMock(return_value="LG Display và Rorze đang tuyển.")
    monkeypatch.setattr(runner, "_agent_turn", agent_turn)

    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="bên mình đang tuyển gì?"),
        deps)

    assert result == {"outcome": "sent", "reply": "LG Display và Rorze đang tuyển."}
    agent_turn.assert_awaited_once()
    assert direct_reader.calls == 0


@pytest.mark.asyncio
async def test_terse_vacancy_followup_reaches_contextual_direct_llm():
    class _DirectReader:
        async def active_context(self):
            return DirectContext(
                knowledge_base_id="kb-1",
                persona_body="Bạn là tư vấn viên.",
                knowledge_text="LG Display Tràng Duệ đang tuyển công nhân thời vụ.")

    class _DirectAgent:
        calls = 0

        async def direct(self, user_text, *, system, metrics=None):  # noqa: ARG002
            self.calls += 1
            assert "ó viedjc gì" in user_text
            return "LG Display đang tuyển công nhân thời vụ bạn nhé."

    svc, _ = _stub_svc(conv=_FakeConv())
    deps = _deps(_FakeZalo(), conversation=svc)
    direct_agent = _DirectAgent()
    deps.agent = direct_agent
    deps.direct_context = _DirectReader()

    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="ó viedjc gì"),
        deps)

    assert result == {
        "outcome": "direct_context",
        "reply": "LG Display đang tuyển công nhân thời vụ bạn nhé.",
    }
    assert direct_agent.calls == 1


@pytest.mark.asyncio
async def test_vacancy_salary_followup_reaches_contextual_direct_llm():
    class _DirectReader:
        async def active_context(self):
            return DirectContext(
                knowledge_base_id="kb-1",
                persona_body="Bạn là tư vấn viên.",
                knowledge_text=(
                    "Question: LG Display Hải Phòng tuyển vị trí gì?\n\n"
                    "Answer: LG Display Hải Phòng tuyển công nhân thời vụ.\n\n"
                    "Question: Lương của công nhân LG Display là bao nhiêu?\n\n"
                    "Answer: Lương cơ bản hiện tại là 6.030.000 VNĐ/tháng; thu nhập "
                    "ước tính 10-13 triệu VNĐ/tháng khi có tăng ca."
                ))

    class _DirectAgent:
        calls = 0

        async def direct(self, user_text, *, system, metrics=None):  # noqa: ARG002
            self.calls += 1
            assert "luong bao nhieu da" in user_text
            return "Lương cơ bản 6.030.000 VNĐ/tháng; thu nhập 10-13 triệu VNĐ/tháng."

    history = [
        SimpleNamespace(
            sender="WORKER",
            body="bên lG tràng duệ mình đang tuyển ạ"),
        SimpleNamespace(sender="WORKER", body="cho nao cung duoc"),
    ]
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, messages=history)
    deps = _deps(_FakeZalo(), conversation=svc)
    direct_agent = _DirectAgent()
    deps.agent = direct_agent
    deps.direct_context = _DirectReader()
    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="luong bao nhieu da"),
        deps)

    assert result["outcome"] == "direct_context"
    assert "6.030.000 VNĐ/tháng" in result["reply"]
    assert "10-13 triệu VNĐ/tháng" in result["reply"]
    assert direct_agent.calls == 1


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
async def test_owned_oa_turn_enriches_profile_before_agent(monkeypatch):
    conv = _FakeConv(zalo_chat_id="oa:user-42", zalo_channel="oa")
    svc, _ = _stub_svc(conv=conv, owned=True)
    events: list[str] = []

    async def enrich(zalo_id: str, user_id: str) -> bool:
        assert zalo_id == "oa:user-42"
        assert user_id == "user-42"
        events.append("profile")
        return True

    async def agent(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        events.append("agent")
        return "Chào bạn!"

    monkeypatch.setattr(runner, "_agent_turn", agent)
    state = _state()
    state.lock_owner = "00000000-0000-0000-0000-0000000000aa"

    result = await run_turn(
        state,
        _deps(
            _FakeZalo(),
            conversation=svc,
            enrich_oa_profile=enrich))

    assert result["outcome"] == "sent"
    assert events == ["profile", "agent"]


@pytest.mark.asyncio
async def test_oa_profile_timeout_fails_open(monkeypatch):
    conv = _FakeConv(zalo_chat_id="oa:user-42", zalo_channel="oa")
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")

    async def enrich(_zalo_id: str, _user_id: str) -> bool:
        await asyncio.sleep(0.02)
        return True

    monkeypatch.setattr(runner, "OA_PROFILE_LOOKUP_TIMEOUT_SECONDS", 0.001)
    result = await run_turn(
        _state(),
        _deps(
            _FakeZalo(),
            conversation=svc,
            enrich_oa_profile=enrich))

    assert result["outcome"] == "sent"


@pytest.mark.asyncio
async def test_oa_profile_lookup_skips_when_turn_deadline_is_tight(monkeypatch):
    conv = _FakeConv(zalo_chat_id="oa:user-42", zalo_channel="oa")
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    calls: list[tuple[str, str]] = []

    async def enrich(zalo_id: str, user_id: str) -> bool:
        calls.append((zalo_id, user_id))
        return True

    state = _state()
    state.deadline_at_epoch = time.time() + 0.5
    result = await run_turn(
        state,
        _deps(
            _FakeZalo(),
            conversation=svc,
            enrich_oa_profile=enrich))

    assert result["outcome"] == "sent"
    assert calls == []


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
        {
            "chat_id": "z1",
            "user_text": "tôi muốn tìm việc lái xe",
            "bot_output": "Chào bạn!",
            "conversation_version": 1,
        }
    ]


@pytest.mark.asyncio
async def test_direct_vacancy_question_reaches_agent_when_faq_bypass_misses(monkeypatch):
    user_text = "bên bạn có nhận thợ hàn không?"

    class _MissBypass:
        async def try_answer(self, user_text):  # noqa: ARG002
            return None

    captured: dict[str, object] = {}

    async def _grounded_agent(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        captured["user_text"] = user_text
        captured["chat_id"] = chat_id
        captured["recent_messages"] = list(recent_messages)
        return f"LLM saw: {user_text}"

    monkeypatch.setattr(runner, "_agent_turn", _grounded_agent)
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv)
    zalo = _FakeZalo()
    deps = _deps(zalo, conversation=svc, faq_bypass=_MissBypass())
    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text)

    result = await run_turn(state, deps)

    assert result["outcome"] == "sent"
    assert result["reply"] == f"LLM saw: {user_text}"
    assert captured["user_text"] == user_text
    assert captured["chat_id"] == "z1"
    assert recorded[0]["stage_timings"]["lane"] == "agent"


@pytest.mark.asyncio
async def test_exact_reported_vacancy_question_still_reaches_llm(monkeypatch):
    from app.graph.ports import FaqBypassResult

    user_text = (
        "mình nhà ở quoán toan _hp gần lG tràng duệ."
        "bên lG tràng duệ mình đang tuyển ạ"
    )
    canonical_answer = (
        "LG Display Hải Phòng tuyển công nhân thời vụ làm sản xuất và kiểm tra "
        "màn hình điện tử tại Khu công nghiệp Tràng Duệ, An Dương, Hải Phòng."
    )

    class _CanonicalFaq:
        query = ""

        async def try_answer(self, query):
            self.query = query
            return FaqBypassResult(
                answer=canonical_answer,
                faq_id="lg-display-vacancy",
                tier="hybrid",
                score=0.93,
                runner_up_score=0.61)

    _stub_agent(monkeypatch, canonical_answer)
    bypass = _CanonicalFaq()
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv)

    result = await run_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text),
        _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert result == {"outcome": "sent", "reply": canonical_answer}
    assert bypass.query == ""


@pytest.mark.parametrize(
    "user_text",
    [
        "giới thiệu các vị trí đang tuyển",
        "hiện tại có những công việc gì đang tuyển",
        "LG tuyển thợ hàn không?",
    ])
@pytest.mark.asyncio
async def test_vacancy_prompts_reach_agent_when_faq_bypass_misses(monkeypatch, user_text):
    class _MissBypass:
        async def try_answer(self, user_text):  # noqa: ARG002
            return None

    captured: dict[str, object] = {}

    async def _grounded_agent(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        captured["user_text"] = user_text
        captured["chat_id"] = chat_id
        captured["recent_messages"] = list(recent_messages)
        return f"LLM saw: {user_text}"

    monkeypatch.setattr(runner, "_agent_turn", _grounded_agent)
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv)
    zalo = _FakeZalo()
    deps = _deps(zalo, conversation=svc, faq_bypass=_MissBypass())
    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text)

    result = await run_turn(state, deps)

    assert result["outcome"] == "sent"
    assert result["reply"] == f"LLM saw: {user_text}"
    assert captured["user_text"] == user_text
    assert captured["chat_id"] == "z1"
    assert recorded[0]["stage_timings"]["lane"] == "agent"


@pytest.mark.asyncio
async def test_vacancy_followup_reaches_agent_with_scoped_query_when_faq_bypass_misses(monkeypatch):
    class _MissBypass:
        query = ""

        async def try_answer(self, user_text):
            self.query = user_text
            return None

    history = [SimpleNamespace(sender="WORKER", body="bên bạn tuyển thợ hàn CO2 đúng ko?")]
    captured: dict[str, object] = {}

    async def _grounded_agent(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        captured["user_text"] = user_text
        captured["recent_messages"] = list(recent_messages)
        return f"LLM saw follow-up: {user_text}"

    monkeypatch.setattr(runner, "_agent_turn", _grounded_agent)
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, messages=history)
    zalo = _FakeZalo()
    bypass = _MissBypass()
    deps = _deps(zalo, conversation=svc, faq_bypass=bypass)
    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="lương bao nhiêu?")

    result = await run_turn(state, deps)

    assert result["outcome"] == "sent"
    assert result["reply"] == "LLM saw follow-up: lương bao nhiêu?"
    assert captured["user_text"] == "lương bao nhiêu?"
    assert captured["recent_messages"][0].body == "bên bạn tuyển thợ hàn CO2 đúng ko?"
    assert bypass.query == ""
    assert recorded[0]["stage_timings"]["lane"] == "agent"


@pytest.mark.asyncio
async def test_ownership_lost_during_generation_suppresses_send(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=False)
    _stub_agent(monkeypatch, "Chào bạn!")
    persisted: list[dict] = []
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc, persist=persisted.append))

    assert res["outcome"] == "suppressed"
    assert zalo.sent == []  # takeover during generation -> do not send
    assert persisted == []  # extraction only runs after a real send


@pytest.mark.asyncio
async def test_lock_owner_lost_before_turn_suppresses_without_pending(monkeypatch):
    """A stale job whose lock owner no longer matches must not create UI chrome,
    call the agent, or send a status/answer message."""

    class _Svc:
        def __init__(self) -> None:
            self.pending_calls = 0

        async def get(self, _id):
            return _FakeConv(zalo_chat_id="oa:user-42", zalo_channel="oa")

        async def last_messages(self, c, limit):
            raise AssertionError("history should not load after owner loss")

        async def record_bot_pending(self, c):
            self.pending_calls += 1
            raise AssertionError("stale owner must not create PENDING")

        async def recheck_ownership(self, c, version_at_start, lock_owner=None):
            assert lock_owner == "00000000-0000-0000-0000-0000000000aa"
            return False

        async def record_bot_outcome(self, c, **kw):
            raise AssertionError("stale owner must not record outcome")

    async def _must_not_run(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        raise AssertionError("agent must not run after owner loss")

    monkeypatch.setattr(runner, "_agent_turn", _must_not_run)
    svc = _Svc()
    zalo = _FakeZalo()
    state = _state()
    state.lock_owner = "00000000-0000-0000-0000-0000000000aa"
    profile_calls: list[tuple[str, str]] = []

    async def enrich(zalo_id: str, user_id: str) -> bool:
        profile_calls.append((zalo_id, user_id))
        return True

    res = await run_turn(
        state,
        _deps(zalo, conversation=svc, enrich_oa_profile=enrich))

    assert res == {"outcome": "suppressed", "reason": "lock_owner_lost"}
    assert svc.pending_calls == 0
    assert zalo.sent == []
    assert profile_calls == []


@pytest.mark.asyncio
async def test_ownership_refreshes_are_column_scoped(monkeypatch):
    """The pre-recheck and pre-claim refreshes reload exactly the ownership
    columns — never the full row with its contact/channel_identity selectin
    cascade — while the takeover verdicts still flow through the port."""
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    db = _FakeDB()
    state = _state()
    state.lock_owner = "00000000-0000-0000-0000-0000000000aa"

    res = await run_turn(state, _deps(_FakeZalo(), conversation=svc, db=db))

    assert res["outcome"] == "sent"
    # One column-scoped refresh before the ownership recheck, one before the
    # claim; both carry the exhaustive ownership column set (dropping any of
    # them would let a takeover slip past the stale identity-map snapshot).
    expected = tuple(runner._OWNERSHIP_REFRESH_COLUMNS)
    assert db.refresh_calls == [expected, expected]


@pytest.mark.asyncio
async def test_zalo_send_failure_is_reported_as_send_failed(monkeypatch):
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    zalo = _FakeZalo(results=[_SendResult(ok=False, error="zalo_rate_limited")])

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert res["outcome"] == "send_failed"
    assert res["reason"] == "zalo_rate_limited"
    assert res["reply"] == "Chào bạn!"
    # A definite rejection (no error_class) stays FAILED — the reconciler may retry.
    assert recorded[0]["delivery_status"] is None  # no override → FAILED computed downstream


@pytest.mark.asyncio
async def test_zalo_ambiguous_send_timeout_is_send_unknown(monkeypatch):
    """Transport timeout after the request may have reached Zalo → SEND_UNKNOWN."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    zalo = _FakeZalo(
        results=[
            _SendResult(ok=False, error="transport error: read timeout", error_class="read_timeout")
        ]
    )

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert res["outcome"] == "send_unknown"
    assert res["reason"] == "transport error: read timeout"
    assert res["reply"] == "Chào bạn!"
    # The override routes to SEND_UNKNOWN (non-retriable) — closes the duplicate window.
    from app.models.conversation import DeliveryStatus

    assert recorded[0]["delivery_status"] is DeliveryStatus.SEND_UNKNOWN


@pytest.mark.asyncio
async def test_zalo_connect_error_stays_retryable_failed(monkeypatch):
    """A pre-send connection failure (definitely not sent) stays retryable FAILED."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    zalo = _FakeZalo(
        results=[
            _SendResult(
                ok=False, error="transport error: connect failed", error_class="connect_error"
            )
        ]
    )

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert res["outcome"] == "send_failed"
    assert recorded[0]["delivery_status"] is None  # no override → FAILED (retryable)


@pytest.mark.asyncio
async def test_agent_exception_stays_silent(monkeypatch):
    """An agent crash keeps quiet: nothing is sent, the turn is SUPPRESSED.

    An "internal error" text is an engineer-facing detail — the candidate sees
    nothing, the failure lives in the structured log, and the audit row records
    the suppressed outcome so the per-chat mutex still clears.
    """
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, ValueError("agent blew up"))
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert zalo.sent == []  # nothing goes to the customer
    assert res["reply"] == ""
    # Pinned here so a refactor does not silently change the mapping: the turn
    # keeps the "error" outcome label even though nothing was sent.
    assert res["outcome"] == "error"
    assert recorded and recorded[0]["reply"] == ""
    assert recorded[0]["sent"] is False


@pytest.mark.asyncio
async def test_llm_throttle_propagates_uncaught(monkeypatch):
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, LLMThrottled())

    with pytest.raises(LLMThrottled):
        await run_turn(_state(), _deps(_FakeZalo(), conversation=svc))


@pytest.mark.asyncio
async def test_flagged_reply_stays_silent_without_llm_judge(monkeypatch):
    """A reply the fast filter flags (nothing survives cleaning) keeps quiet —
    no second LLM call, no canned redirect.

    The safety LLM judge was removed (it p50'd at 10.3s, as expensive as the
    agent itself), and so was the lexical blocklist. The only remaining redirect
    is structural: the reply cleaned to nothing, so there is no text to send.
    """
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    # Reasoning-only output: nothing survives cleaning.
    _stub_agent(monkeypatch, "<think>chỉ có phần suy luận</think>")

    zalo = _FakeZalo()
    res = await run_turn(
        _state(),
        _deps(zalo, conversation=svc))

    assert res["outcome"] == "suppressed"
    assert res["reply"] == ""
    assert zalo.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_reply", "expected_reply"),
    [
        # These used to be judged by keyword or truncated by the reply-policy
        # layer. With it removed the generated answer ships as written.
        (
            "Anh sẽ đóng vai trò công nhân sản xuất màn hình.",
            "Anh sẽ đóng vai trò công nhân sản xuất màn hình."),
        (
            "Công ty bỏ qua yêu cầu bằng cấp và kinh nghiệm ạ.",
            "Công ty bỏ qua yêu cầu bằng cấp và kinh nghiệm ạ."),
        ("x" * 2000, "x" * 2000),
        ("Thông tin tuyển dụng đã được xác minh.", "Thông tin tuyển dụng đã được xác minh."),
    ])
async def test_generated_reply_is_never_retried(
    monkeypatch, raw_reply, expected_reply
):
    calls = 0

    async def _agent(*args, **kwargs):  # noqa: ARG001
        nonlocal calls
        calls += 1
        return raw_reply

    monkeypatch.setattr(runner, "_agent_turn", _agent)
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)

    result = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc))

    assert calls == 1
    assert result["reply"] == expected_reply
    timings = recorded[0]["stage_timings"]
    assert "generation_retry_count" not in timings
    # No reply-policy trigger is stamped any more: the boundary only strips
    # provider thinking, it does not judge or truncate the answer.
    assert "safety_trigger" not in timings


@pytest.mark.asyncio
async def test_stray_code_fence_ships_as_generated(monkeypatch):
    """A reply containing a stray code fence is sent exactly as generated.

    The removed reply-policy layer used to strip markdown fences before sending.
    With it gone the converged boundary only drops provider thinking, so a fence
    reaches the candidate verbatim — no content is rewritten or discarded.
    """
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    raw = "Bạn cần mang CCCD. ```print(1)``` Hẹn gặp lúc 8h nhé."
    _stub_agent(monkeypatch, raw)

    zalo = _FakeZalo()
    res = await run_turn(
        _state(),
        _deps(zalo, conversation=svc))

    assert res["outcome"] == "sent"
    assert res["reply"] == raw
    assert zalo.sent[0][1] == res["reply"]


# ---------------------------------------------------------------------------
# No hard cap on the agent (advisory deadline only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_runs_to_completion_past_deadline(monkeypatch):
    """No hard cap: an agent that outlasts the propagated deadline is NOT cancelled
    — its real reply is sent. Cancelling live LLM calls mid-generation produced
    excessive TIMEOUT fallbacks in prod, so the deadline is advisory (FAQ-bypass
    budget only) and never kills the agent turn."""
    from app.core.config import get_settings

    # Would have capped the agent at 0.1s pre-change; now has no enforcing effect.
    monkeypatch.setattr(get_settings(), "agent_max_seconds", 0.1)

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)

    async def _slow_agent(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        await asyncio.sleep(0.3)  # well past the 0.1s former cap
        return "Câu trả lời thật của tôi."

    monkeypatch.setattr(runner, "_agent_turn", _slow_agent)

    zalo = _FakeZalo()
    state = _state()
    # Deadline already expired — pre-change this skipped the agent (TIMEOUT_REPLY);
    # now the agent still runs and its real answer is sent.
    state.received_at_epoch = time.time() - 10
    state.deadline_at_epoch = time.time() - 1

    res = await run_turn(state, _deps(zalo, conversation=svc))

    assert res["outcome"] == "sent"
    assert res["reply"] == "Câu trả lời thật của tôi."
    assert zalo.sent and zalo.sent[0][1] == "Câu trả lời thật của tôi."


# ---------------------------------------------------------------------------
# Active-status signal: typing pulses only, NO filler/ack message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_turn_pulses_typing_but_sends_no_filler(monkeypatch):
    """A slow turn pulses the native typing indicator but never sends a filler /
    "still working" message — the user sees only the real answer. (The ack was
    removed: it was redundant with the typing indicator on the Bot channel.)"""
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)

    async def _slow_agent(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        # A single yield is enough: the heartbeat pulses typing immediately on its
        # first slice (next_typing starts at 0), so ordering — pulse before the
        # answer lands — is guaranteed by task scheduling, not by a wall-clock
        # race against the ~0.5s loop tick.
        await asyncio.sleep(0.05)
        return "Câu trả lời thật của tôi."

    monkeypatch.setattr(runner, "_agent_turn", _slow_agent)

    zalo = _FakeZalo()
    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    sent_texts = [text for _, text in zalo.sent]
    assert res["outcome"] == "sent"
    assert sent_texts == ["Câu trả lời thật của tôi."]  # only the real answer, no filler
    assert zalo.actions.count("typing") >= 1  # typing indicator still pulses


@pytest.mark.asyncio
async def test_fast_turn_sends_no_filler(monkeypatch):
    """A turn that answers quickly sends only its reply — no filler/ack message."""
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")  # returns immediately, no yield
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    sent_texts = [text for _, text in zalo.sent]
    assert res["outcome"] == "sent"
    assert sent_texts == ["Chào bạn!"]


# ---------------------------------------------------------------------------
# Final-answer routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_greeting_reaches_agent_and_never_uses_a_template(monkeypatch):
    """Every normal inbound message is finalized by the LLM, including greetings."""
    _stub_agent(monkeypatch, "Chào bạn, tôi có thể hỗ trợ tìm việc tại LG Display.")
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    persisted: list[dict] = []
    zalo = _FakeZalo()

    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="chào bạn")
    res = await run_turn(state, _deps(zalo, conversation=svc, persist=persisted.append))

    assert res["outcome"] == "sent"
    assert res["reply"] == "Chào bạn, tôi có thể hỗ trợ tìm việc tại LG Display."
    assert zalo.sent == [("z1", "Chào bạn, tôi có thể hỗ trợ tìm việc tại LG Display.")]
    assert persisted[0]["user_text"] == "chào bạn"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text",
    ["hello ban", "cảm ơn bạn nhe", "tạm biệt", "bye", "bạn giúp gì được"])
async def test_small_talk_variants_reach_agent(monkeypatch, user_text):
    _stub_agent(monkeypatch, "Phản hồi từ LLM")
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    persisted: list[dict] = []

    result = await run_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text),
        _deps(_FakeZalo(), conversation=svc, persist=persisted.append))

    assert result["outcome"] == "sent"
    assert result["reply"] == "Phản hồi từ LLM"
    assert persisted[0]["user_text"] == user_text


@pytest.mark.asyncio
async def test_mixed_small_talk_message_reaches_agent(monkeypatch):
    _stub_agent(monkeypatch, "Tôi đã ghi nhận.")
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    persisted: list[dict] = []
    user_text = "Cảm ơn, tôi đang kiểm tra bot"

    result = await run_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text),
        _deps(_FakeZalo(), conversation=svc, persist=persisted.append))

    assert result["outcome"] == "sent"
    assert result["reply"] == "Tôi đã ghi nhận."
    assert persisted[0]["user_text"] == user_text
    assert persisted[0]["conversation_version"] == 1


class _FakeFaqBypass:
    """FaqBypassPort stub: returns a fixed result, or raises, so the runner's
    bypass branch is pinned without any DB / embedder."""

    def __init__(self, result=None, exc=None) -> None:
        self._result = result
        self._exc = exc

    async def try_answer(self, user_text):
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.mark.asyncio
async def test_faq_bypass_hit_cannot_short_circuit_llm(monkeypatch):
    """Even a confident legacy FAQ hit cannot become the final bot response."""
    from app.graph.ports import FaqBypassResult

    _stub_agent(monkeypatch, "Câu trả lời từ LLM")

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    persisted: list[dict] = []
    zalo = _FakeZalo()
    bypass = _FakeFaqBypass(
        result=FaqBypassResult(answer="Câu trả lời FAQ", faq_id="abc", tier="hybrid", score=0.9)
    )

    res = await run_turn(
        _state(),
        _deps(zalo, conversation=svc, persist=persisted.append, faq_bypass=bypass))

    assert res["outcome"] == "sent"
    assert res["reply"] == "Câu trả lời từ LLM"
    assert zalo.sent == [("z1", "Câu trả lời từ LLM")]
    assert persisted == [
        {
            "chat_id": "z1",
            "user_text": "tôi muốn tìm việc lái xe",
            "bot_output": "Câu trả lời từ LLM",
            "conversation_version": 1,
        }
    ]


@pytest.mark.asyncio
async def test_faq_bypass_miss_falls_through_to_agent(monkeypatch):
    """A bypass abstain (None) leaves the turn to the agent as usual."""
    _stub_agent(monkeypatch, "trả lời từ agent")
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    bypass = _FakeFaqBypass(result=None)

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert res["outcome"] == "sent"
    assert res["reply"] == "trả lời từ agent"


@pytest.mark.asyncio
async def test_faq_bypass_exception_falls_through_to_agent(monkeypatch):
    """An adapter exception must never break the turn — it abstains to the agent."""
    _stub_agent(monkeypatch, "trả lời từ agent")
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    bypass = _FakeFaqBypass(exc=RuntimeError("adapter blew up"))

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert res["outcome"] == "sent"
    assert res["reply"] == "trả lời từ agent"


@pytest.mark.asyncio
async def test_faq_bypass_timeout_falls_through_to_agent(monkeypatch):
    """A bypass that exceeds its time-box abstains and the agent handles the turn."""
    _stub_agent(monkeypatch, "trả lời từ agent")
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    bypass = _FakeFaqBypass(exc=asyncio.TimeoutError())

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert res["outcome"] == "sent"
    assert res["reply"] == "trả lời từ agent"


@pytest.mark.asyncio
async def test_grounded_reply_survives_former_blocklist_wording(monkeypatch):
    """Regression for prod bot_run 613.

    The model retrieved LG Display via get_product_features and wrote a correct
    answer; a lexical rule matched ordinary Vietnamese inside it and replaced the
    whole thing with a content-free hedge. Nothing may discard a reply on wording.
    """
    reply = (
        "Làm tại LG Display là sản xuất và kiểm tra màn hình tivi, máy tính, điện "
        "thoại ạ. Công ty có đào tạo trước khi vào làm và công việc này đóng vai "
        "trò quan trọng trong dây chuyền ạ."
    )
    _stub_agent(monkeypatch, reply)

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert res["outcome"] == "sent"
    assert res["reply"] == reply
    assert zalo.sent == [("z1", reply)]


@pytest.mark.asyncio
async def test_reasoning_referencing_system_prompt_keeps_grounded_answer(monkeypatch):
    """Provider deliberation never reaches the user, and never costs the answer.

    A reasoning model routinely writes "theo system prompt …" while deciding how
    to answer. That text is stripped; the grounded answer after it is sent.
    """
    raw = (
        "<think>Người dùng hỏi công ty Việt Pháp ở tỉnh nào. Theo system prompt "
        "và KB, VFIC đặt tại KCN Tràng Duệ, An Dương, Hải Phòng. Trả lời ngắn gọn."
        "</think>"
        "Công ty Việt Pháp (VFIC) đặt tại Khu công nghiệp Tràng Duệ, huyện An "
        "Dương, TP. Hải Phòng."
    )
    _stub_agent(monkeypatch, raw)

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc))

    assert res["outcome"] == "sent"
    assert res["reply"] != ""
    assert "Hải Phòng" in res["reply"]
    assert "system prompt" not in res["reply"]


@pytest.mark.asyncio
async def test_overlong_clean_reply_ships_as_generated(monkeypatch):
    """A clean (no code/JSON) reply over 1800 chars ships unchanged.

    A detailed job-presentation with multiple benefit lines can legitimately
    exceed 1800 chars — the persona explicitly exempts the job template from
    the 300-char cadence. With the deterministic reply-policy layer removed the
    converged boundary no longer truncates: the answer is sent exactly as
    generated, with only provider thinking stripped.
    """
    long_reply = "Tên công việc: Operator LG Display\n" + (
        "Quyền lợi: bảo hiểm, phụ cấp, KTX. " * 100
    )
    assert len(long_reply) > 1800  # sanity

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, long_reply)

    zalo = _FakeZalo()
    res = await run_turn(
        _state(),
        _deps(zalo, conversation=svc))

    assert res["outcome"] == "sent"
    # The reply is the generated answer, not truncated and not the fallback.
    assert res["reply"] == long_reply
    assert "Mình không trả lời được" not in res["reply"]


# ---------------------------------------------------------------------------
# Adapter-error session safety: a swallowed adapter error must not poison the turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_faq_bypass_is_not_called(monkeypatch):
    db = _FakeDB()

    class _BoomBypass:
        async def try_answer(self, _text):  # noqa: ARG002
            db._poisoned = True  # adapter query failed, poisoning the session
            raise RuntimeError("faq_bypass DB error")

    conv = _FakeConv()
    svc, _recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "agent reply")  # agent lane succeeds after abstain

    deps = _deps(_FakeZalo(), conversation=svc, faq_bypass=_BoomBypass(), db=db)
    res = await run_turn(_state(), deps)

    assert db.rollbacks == 0
    assert db._poisoned is False
    assert res["outcome"] == "sent"


@pytest.mark.asyncio
async def test_agent_error_rolls_back_session_before_silent_record(monkeypatch):
    """When the agent path raises after touching the session, run_turn must roll
    back before the silent outcome recording — otherwise the recovery write
    itself raises a rollback error and the audit row is lost.
    """
    db = _FakeDB()

    async def _boom(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        db._poisoned = True  # agent's lead / system-prompt read failed
        raise RuntimeError("agent DB error")

    monkeypatch.setattr(runner, "_agent_turn", _boom)
    conv = _FakeConv()
    svc, _recorded = _stub_svc(conv=conv, owned=True)

    deps = _deps(_FakeZalo(), conversation=svc, db=db)
    res = await run_turn(_state(), deps)

    assert db.rollbacks >= 1, "agent error must roll back before the error reply"
    assert res["outcome"] == "error", "silent recovery must still complete"


# ---------------------------------------------------------------------------
# Per-stage stage_timings capture (Option A metrics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_timings_records_agent_lane_send_and_total(monkeypatch):
    """Agent path on an owned send threads stage_timings into record_bot_outcome
    with lane='agent', the lead stamp + the split llm_queue/llm_model stamps
    collected inside _agent_turn, plus send_ms and total_ms."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)

    async def _fake(
        state,
        deps,
        user_text,
        *,
        provider=None,
        chat_id,
        recent_messages,
        contact_id=None,
        timings=None,
        decisions=None,
        lead_row=None):  # noqa: ARG001
        # Emulate the real _agent_turn stamping into the shared timings dict.
        # The LLM stage is now the split llm_queue_ms + llm_model_ms pair
        # (written by MiniMaxAgent.agent, not the monolithic llm_ms).
        if timings is not None:
            timings["lead_ms"] = 111
            timings["llm_queue_ms"] = 200
            timings["llm_model_ms"] = 799
            timings["system_prompt_ms"] = 5
        return "Chào bạn!"

    monkeypatch.setattr(runner, "_agent_turn", _fake)
    from app.shared.application.outbound import OutboundTelemetry

    telemetry = OutboundTelemetry(
        adapter="test_adapter",
        adapter_prepare_ms=2,
        provider_request_ms=17,
        provider_attempts=1,
        chunk_count=1,
        result="sent")
    res = await run_turn(
        _state(), _deps(_FakeZalo(results=[_SendResult(telemetry=telemetry)]), conversation=svc)
    )

    assert res["outcome"] == "sent"
    assert recorded, "record_bot_outcome must be called"
    st = recorded[0]["stage_timings"]
    assert st["lane"] == "agent"
    assert st["lead_ms"] == 111  # threaded through from _agent_turn
    assert st["llm_queue_ms"] == 200  # split: semaphore wait
    assert st["llm_model_ms"] == 799  # split: model inference
    assert st["system_prompt_ms"] == 5  # split: persona+index assembly
    assert st["send_ms"] >= 0
    assert st["outbound_adapter"] == "test_adapter"
    assert st["outbound_prepare_ms"] == 2
    assert st["outbound_provider_ms"] == 17
    assert st["outbound_result"] == "sent"
    assert st["total_ms"] >= st["send_ms"]
    # DB path attribution: every DB call in run_turn is timed into db_ms +
    # db_breakdown so a slow query is attributable (the previous blind spot).
    assert "db_ms" in st
    assert st["db_ms"] >= 0
    assert "db_breakdown" in st
    # At least the conversation fetch + record_bot_outcome were timed.
    assert "get_conversation" in st["db_breakdown"]
    assert "record_bot_outcome" in st["db_breakdown"]


@pytest.mark.asyncio
async def test_trace_id_propagates_to_record_bot_outcome(monkeypatch):
    """state.trace_id flows through to record_bot_outcome for BotRun.trace_id stamping."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    state = _state()
    state.trace_id = "abc-123-trace"
    res = await run_turn(state, _deps(_FakeZalo(), conversation=svc))

    assert res["outcome"] == "sent"
    assert recorded[0]["trace_id"] == "abc-123-trace"


@pytest.mark.asyncio
async def test_empty_trace_id_passes_none(monkeypatch):
    """When state.trace_id is empty (legacy/test turns), record_bot_outcome gets None."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")
    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc))  # trace_id=""

    assert res["outcome"] == "sent"
    assert recorded[0]["trace_id"] is None


@pytest.mark.asyncio
async def test_agent_turn_stamps_system_prompt_ms(monkeypatch):
    """The real _agent_turn stamps system_prompt_ms before the LLM call.

    This is the instrumentation that lets the dashboard attribute the
    persona + active-product-index assembly separately from model inference.
    Uses a fake agent so no LLM call is made; build_system_prompt is stubbed
    so no DB / Redis is touched.
    """
    from app.graph.runner import _agent_turn

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            return "reply"

    class _FakeLead:
        async def context(self, *a, **kw):  # noqa: ARG002
            return "", ""

        def instruction(self, q):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kw: kw["current_user_text"])

    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="hi")
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()
    timings: dict = {"lane": "agent"}

    await _agent_turn(
        state,
        deps,
        "hi",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings=timings,
        decisions=TurnDecisions(pleasantry=True, intent="small_talk", intent_confidence=0.9))

    assert "system_prompt_ms" in timings
    assert timings["system_prompt_ms"] >= 0


@pytest.mark.asyncio
async def test_model_tier_metric_follows_the_configured_fast_client(monkeypatch):
    """``stage_timings.model_tier`` must not claim a tier that has no client.

    Prod ran with no fast-tier model configured while the metric still read
    "fast" on every fast-eligible turn, so the performance dashboard reported a
    tier that never served a request. The stamp now follows the client the agent
    actually holds.
    """
    from app.graph.router import TurnRoute
    from app.graph.runner import _agent_turn

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _FakeAgent:
        def __init__(self, fast_llm=None):
            self.fast_llm = fast_llm
            self.use_fast_seen = None

        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            self.use_fast_seen = kwargs.get("use_fast")
            return "Nội dung chuyển hướng"

    class _FakeLead:
        async def context(self, *a, **kw):  # noqa: ARG002
            return "", ""

        def instruction(self, q):  # noqa: ARG002
            return ""

    def _route_without_fast_tier(_text, _decisions):
        # safe_redirect is the only fast-eligible strategy.
        return TurnRoute("out_of_scope", "safe_redirect", reason="off_topic", confidence=0.9)

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kw: kw["current_user_text"])
    monkeypatch.setattr(runner, "route_from_decisions", _route_without_fast_tier)

    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="hi")

    # No fast client injected (the configured-prod case) → primary, and the
    # eligibility flag handed to the agent must be False.
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent(fast_llm=None)
    deps.lead = _FakeLead()
    timings: dict = {"lane": "agent"}
    await _agent_turn(
        state,
        deps,
        "hi",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings=timings,
        decisions=TurnDecisions(degraded=True))
    assert timings["model_tier"] == "primary"
    assert deps.agent.use_fast_seen is False

    # With a fast client wired, the same route is honestly stamped "fast".
    deps_fast = _deps(_FakeZalo(), conversation=object())
    deps_fast.agent = _FakeAgent(fast_llm=object())
    deps_fast.lead = _FakeLead()
    timings_fast: dict = {"lane": "agent"}
    await _agent_turn(
        state,
        deps_fast,
        "hi",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings=timings_fast,
        decisions=TurnDecisions(degraded=True))
    assert timings_fast["model_tier"] == "fast"
    assert deps_fast.agent.use_fast_seen is True


@pytest.mark.asyncio
async def test_rag_vacancy_turn_requires_active_job_catalog_for_exact_reported_message(monkeypatch):
    from app.graph.runner import _agent_turn

    query = (
        "mình nhà ở quán toan _hp gần IG tràng duệ."
        "bên IG tràng duệ mình đang tuyển ạ"
    )
    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            captured.update(kwargs)
            return "LG Display Tràng Duệ đang tuyển."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=query),
        deps,
        query,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="recommend", intent_confidence=0.94, vacancy_listing=True))

    assert reply == "LG Display Tràng Duệ đang tuyển."
    assert captured["allowed_tools"] == ("list_active_jobs",)
    assert captured["lookup_query"] == query
    assert captured["required_tool"] == "list_active_jobs"
    assert captured["required_tool_args"] == {"top_k": 10}


@pytest.mark.asyncio
async def test_focused_rag_detail_forces_project_scoped_category_search(monkeypatch):
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "LG Display làm ca ngày 08:00-20:00 và ca đêm 20:00-08:00."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()
    context = SimpleNamespace(
        state="FOCUSED",
        knowledge_mode="RAG",
        project_slug="lg-display",
        project_name="LG Display")

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="giờ làm của LG"),
        deps,
        "giờ làm của LG",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[
            SimpleNamespace(sender="WORKER", body="LG Display đang tuyển công nhân không?")
        ],
        timings={"lane": "agent"},
        project_context=context,
        decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.9))

    assert reply == "LG Display làm ca ngày 08:00-20:00 và ca đêm 20:00-08:00."
    assert captured["allowed_tools"] == ("search_knowledge",)
    assert captured["required_tool"] == "search_knowledge"
    assert captured["required_tool_args"] == {
        "query": "giờ làm của LG",
        "project_slug": "lg-display",
    }
    assert captured["forced_project_slug"] == "lg-display"


@pytest.mark.asyncio
async def test_cross_project_salary_target_requires_compare_income(monkeypatch):
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "Rorze có bằng chứng đạt mốc 20 triệu."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="lương 20 triệu"),
        deps,
        "lương 20 triệu",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        project_context=SimpleNamespace(
            state="EXPLORE",
            knowledge_mode=None,
            project_slug=None,
            project_name=None),
        decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.9))

    assert reply == "Rorze có bằng chứng đạt mốc 20 triệu."
    assert captured["allowed_tools"] == ("compare_income",)
    assert captured["required_tool"] == "compare_income"
    assert captured["required_tool_args"] == {"target_monthly_vnd": 20_000_000}
    assert "forced_project_slug" not in captured


@pytest.mark.asyncio
async def test_generic_vacancy_listing_requires_active_job_catalog(monkeypatch):
    from app.graph.runner import _agent_turn

    query = "bên mình đang tuyển gì?"
    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            captured.update(kwargs)
            return "Danh sách việc đang tuyển."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=query),
        deps,
        query,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        project_context=SimpleNamespace(
            state="EXPLORE",
            knowledge_mode=None,
            project_slug=None,
            project_name=None),
        decisions=TurnDecisions(intent="recommend", intent_confidence=0.94, vacancy_listing=True))

    assert reply == "Danh sách việc đang tuyển."
    assert captured["allowed_tools"] == ("list_active_jobs",)
    assert captured["required_tool"] == "list_active_jobs"
    assert captured["required_tool_args"] == {"top_k": 10}


@pytest.mark.asyncio
async def test_terse_vacancy_followup_keeps_active_job_catalog_authority(monkeypatch):
    from app.graph.runner import _agent_turn

    query = "lg thì sao"
    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            captured.update(kwargs)
            return "LG Display đang tuyển công nhân thời vụ."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=query),
        deps,
        query,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[
            SimpleNamespace(sender="WORKER", body="có bao nhiêu nhà máy đang tuyển")
        ],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="general", intent_confidence=0.5, recent_vacancy=True))

    assert reply == "LG Display đang tuyển công nhân thời vụ."
    assert captured["allowed_tools"] == ("list_active_jobs",)
    assert captured["required_tool"] == "list_active_jobs"
    assert captured["required_tool_args"] == {"top_k": 10}


@pytest.mark.asyncio
async def test_rag_vacancy_salary_followup_scopes_knowledge_query_to_vacancy_thread(monkeypatch):
    from app.graph.runner import _agent_turn

    query = "luong bao nhieu da"
    history = [
        SimpleNamespace(
            sender="WORKER",
            body=(
                "mình nhà ở quoán toan _hp gần lG tràng duệ."
                "bên lG tràng duệ mình đang tuyển ạ"
            )),
        SimpleNamespace(sender="WORKER", body="cho nao cung duoc"),
    ]
    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            captured.update(kwargs)
            return "safe reply"

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=query),
        deps,
        query,
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=history,
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.9, recent_vacancy=True))

    assert captured["allowed_tools"] == ("get_product_features", "search_knowledge")
    assert "lG tràng duệ" in str(captured["lookup_query"])
    assert query in str(captured["lookup_query"])
    assert "required_tool" not in captured


@pytest.mark.asyncio
async def test_agent_turn_does_not_append_collection_question(monkeypatch):
    """Single-ownership regression: _agent_turn returns the raw agent reply.

    The canonical lead-collection CTA is NOT appended — the LLM is the sole
    asker. Previously ensure_lead_collection_question would tack a phone/name
    question onto the reply, producing duplicate asks when the LLM had already
    asked in its own wording. This test locks in that the append is gone.
    """
    from app.graph.runner import _agent_turn

    raw_reply = "Dạ, tôi có thể hỗ trợ bạn về lương và ca làm tại LG Display."

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        assert provider == "zalo_bot"
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            return raw_reply

    class _FakeLead:
        async def context(self, *a, **kw):  # noqa: ARG002
            # Return a non-empty collection question to prove it is NOT used
            # to append anything to the reply.
            return "", "Bạn cho tôi xin số điện thoại để VFIC liên hệ nhé?"

        def instruction(self, q):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kw: kw["current_user_text"])

    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="hi")
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    result = await _agent_turn(
        state,
        deps,
        "hi",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(pleasantry=True, intent="small_talk", intent_confidence=0.9))
    # The reply must be returned verbatim — no appended canonical question.
    assert result == raw_reply
    assert "số điện thoại" not in result


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_terminally_unreachable_recipient_skips_generation(monkeypatch):
    """A recipient the provider permanently rejects must not burn a ~9 s turn.

    Prod: 21 of 284 turns were sends rejected with `user_id is invalid`; each one
    paid a full generation that could never be delivered. The dispatcher records
    the terminal mark on the first such failure; the turn path must stand down
    before Jev / the model call.
    """
    calls: list[tuple[str, str]] = []

    async def _marked(channel, recipient_id):
        calls.append((channel, recipient_id))
        return True

    # Any model call would be a wasted ~9 s turn.
    _stub_agent(monkeypatch, AssertionError("generation must not run"))

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    deps = _deps(_FakeZalo(), conversation=svc)
    deps.recipient_unreachable = _marked
    res = await run_turn(_state(), deps)

    assert res["outcome"] == "suppressed"
    assert calls and calls[0][1] == "z1"
    assert recorded[0]["reply"] == ""
    assert recorded[0]["stage_timings"]["lane"] == "recipient_unreachable"


@pytest.mark.asyncio
async def test_reachable_recipient_still_runs_the_turn(monkeypatch):
    """Fail-open: an unmarked recipient (or a Redis error) must proceed normally."""
    async def _not_marked(channel, recipient_id):  # noqa: ARG001
        return False

    _stub_agent(monkeypatch, "Chào bạn!")

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    deps = _deps(_FakeZalo(), conversation=svc)
    deps.recipient_unreachable = _not_marked
    res = await run_turn(_state(), deps)

    assert res["outcome"] == "sent"
    assert recorded[0]["stage_timings"]["lane"] == "agent"


async def test_stage_timings_records_agent_lane_for_greeting(monkeypatch):
    """A greeting is attributed to the LLM agent lane, not a template lane."""
    _stub_agent(monkeypatch, "Chào bạn!")
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="chào bạn")
    res = await run_turn(state, _deps(_FakeZalo(), conversation=svc))

    assert res["outcome"] == "sent"
    assert res["reply"] == "Chào bạn!"
    st = recorded[0]["stage_timings"]
    assert st["lane"] == "agent"
    assert st["total_ms"] >= 0


@pytest.mark.asyncio
async def test_faq_bypass_candidate_records_agent_lane(monkeypatch):
    """Legacy FAQ candidates do not create a factual final-answer lane."""
    from app.graph.ports import FaqBypassResult

    _stub_agent(monkeypatch, "Trả lời từ agent")
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    bypass = _FakeFaqBypass(
        result=FaqBypassResult(answer="Câu trả lời FAQ", faq_id="x", tier="hybrid", score=0.9)
    )
    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert res["outcome"] == "sent"
    assert recorded[0]["stage_timings"]["lane"] == "agent"


@pytest.mark.asyncio
async def test_faq_bypass_high_margin_does_not_replace_llm(monkeypatch):
    from app.graph.ports import FaqBypassResult

    _stub_agent(monkeypatch, "Trả lời từ agent")
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    bypass = _FakeFaqBypass(
        result=FaqBypassResult(
            answer="Câu trả lời FAQ",
            faq_id="x",
            tier="hybrid",
            score=0.90,
            runner_up_score=0.70,  # margin 0.20 > 0.03 default
        )
    )
    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert res == {"outcome": "sent", "reply": "Trả lời từ agent"}
    assert recorded[0]["outcome_metadata"] is None


@pytest.mark.asyncio
async def test_faq_bypass_low_margin_reaches_agent_without_bypass_metadata(monkeypatch):
    from app.graph.ports import FaqBypassResult

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Trả lời từ agent")
    bypass = _FakeFaqBypass(
        result=FaqBypassResult(
            answer="Câu trả lời FAQ sai",
            faq_id="x",
            tier="hybrid",
            score=0.85,
            runner_up_score=0.84,  # margin 0.01 < 0.03 default → abstain
        )
    )
    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert res["outcome"] == "sent"
    assert res["reply"] == "Trả lời từ agent"
    assert recorded[0]["outcome_metadata"] is None
    assert recorded[0]["stage_timings"].get("faq_abstained") is None


@pytest.mark.asyncio
async def test_faq_bypass_without_runner_up_still_reaches_llm(monkeypatch):
    from app.graph.ports import FaqBypassResult

    _stub_agent(monkeypatch, "Trả lời từ agent")
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    bypass = _FakeFaqBypass(
        result=FaqBypassResult(
            answer="Câu trả lời FAQ",
            faq_id="x",
            tier="exact",
            score=0.50,
            runner_up_score=None,  # single result → never abstain
        )
    )
    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, faq_bypass=bypass))

    assert res == {"outcome": "sent", "reply": "Trả lời từ agent"}
    assert recorded[0]["outcome_metadata"] is None


@pytest.mark.asyncio
async def test_stage_timings_suppressed_has_no_send_stage(monkeypatch):
    """Ownership lost during generation -> suppressed: lane still 'agent', total_ms
    recorded, but no send_ms (the send was never attempted)."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=False)
    _stub_agent(monkeypatch, "Chào bạn!")
    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc))

    assert res["outcome"] == "suppressed"
    st = recorded[0]["stage_timings"]
    assert st["lane"] == "agent"
    assert "send_ms" not in st
    assert st["total_ms"] >= 0


@pytest.mark.asyncio
async def test_stage_timings_captures_preamble_and_webhook_to_pickup(monkeypatch):
    """When the worker stamps received_at_epoch + preamble_start_epoch + queue_depth,
    the turn records the enqueue→pickup gap, the preamble, and the queue depth."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    _stub_agent(monkeypatch, "Chào bạn!")

    state = _state()
    state.received_at_epoch = time.time() - 0.4
    state.preamble_start_epoch = time.time() - 0.2  # 0.2s after webhook receipt
    state.queue_depth = 3

    res = await run_turn(state, _deps(_FakeZalo(), conversation=svc))

    assert res["outcome"] == "sent"
    st = recorded[0]["stage_timings"]
    assert st["webhook_to_pickup_ms"] >= 150  # ~0.2s enqueue→pickup
    assert st["preamble_ms"] >= 0
    assert st["queue_depth"] == 3
    assert st["end_to_end_ms"] >= 350  # measured from webhook receipt


# --- empty-candidate defense-in-depth --------------------------------------


@pytest.mark.asyncio
async def test_empty_agent_candidate_suppressed_without_send(monkeypatch):
    """An empty agent result must stay silent: nothing sent, suppressed audit row.

    Regression for the empty "Gửi lỗi" bubble: without the guard, the empty
    candidate is stamped onto the pending row (body="") and, when the send
    later fails, renders as a blank failed bubble with no diagnosable content.
    """

    async def _empty_agent(*args, **kwargs):  # noqa: ARG001
        return ""

    monkeypatch.setattr(runner, "_agent_turn", _empty_agent)

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, owned=True)
    zalo = _FakeZalo()
    state = BotRunState(
        conversation_id=CONV_ID,
        version_at_start=1,
        # Any message now reaches the agent before the empty-reply guard runs.
        user_text="bên bạn có tuyển dụng gì không?")

    res = await run_turn(state, _deps(zalo, conversation=svc))

    # Empty agent output keeps quiet: nothing sent, SUPPRESSED audit row.
    assert res["outcome"] == "suppressed"
    assert res["reply"] == ""
    assert zalo.sent == []
    assert recorded and recorded[0]["reply"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\n\t  "])
async def test_whitespace_agent_candidate_stays_silent(monkeypatch, blank):
    """Whitespace-only agent results follow the same keep-quiet path."""

    async def _blank_agent(*args, **kwargs):  # noqa: ARG001
        return blank

    monkeypatch.setattr(runner, "_agent_turn", _blank_agent)

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    zalo = _FakeZalo()
    state = BotRunState(
        conversation_id=CONV_ID, version_at_start=1, user_text="cho mình hỏi lương"
    )

    res = await run_turn(state, _deps(zalo, conversation=svc))

    assert res["outcome"] == "suppressed"
    assert res["reply"] == ""
    assert zalo.sent == []


# ---------------------------------------------------------------------------
# Candidate gender inference (Jev judgment -> blank lead.gender)
# ---------------------------------------------------------------------------


class _LeadGenderStub:
    """Capture gender reads/writes; honour blank-only vs override like the adapter."""

    def __init__(self, stored: str = "", *, raises: bool = False) -> None:
        self.stored = stored
        self.raises = raises
        self.calls: list[dict] = []

    async def stored_gender(self, chat_id: str, contact_id: str | None = None) -> str:
        if self.raises:
            raise RuntimeError("gender lookup boom")
        return self.stored

    async def record_inferred_gender(
        self,
        chat_id: str,
        gender: str,
        *,
        contact_id: str | None = None,
        override: bool = False) -> bool:
        self.calls.append(
            {"chat_id": chat_id, "gender": gender, "contact_id": contact_id, "override": override}
        )
        wrote = not self.stored or override
        if wrote:
            self.stored = gender
        return wrote


def _decisions_port(decisions: TurnDecisions):
    """A TurnDecisionsPort stub that records the kwargs the runner sent."""
    port = SimpleNamespace(calls=[])

    async def decide_turn(**kwargs):
        port.calls.append(kwargs)
        return decisions

    port.decide_turn = decide_turn
    return port


async def _run_gender_turn(
    monkeypatch, *, decisions, gender_stub, state=None, conv=None, reply="Dạ em chào Anh/chị ạ"
):
    _stub_agent(monkeypatch, reply)
    conv = conv or _FakeConv()
    svc, _ = _stub_svc(conv=conv)
    deps = _deps(_FakeZalo(), conversation=svc)
    deps.turn_decisions = _decisions_port(decisions)
    deps.lead_gender = gender_stub
    result = await run_turn(state or _state(), deps)
    return result, deps


@pytest.mark.asyncio
async def test_confident_gender_is_recorded_on_blank_lead(monkeypatch):
    stub = _LeadGenderStub(stored="")
    result, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="female", gender_confidence=0.9),
        gender_stub=stub)
    assert result["outcome"] == "sent"
    assert stub.calls == [
        {"chat_id": "z1", "gender": "female", "contact_id": None, "override": False}
    ]
    assert stub.stored == "female"


@pytest.mark.asyncio
async def test_unknown_gender_is_not_recorded(monkeypatch):
    stub = _LeadGenderStub(stored="")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="unknown", gender_confidence=0.99),
        gender_stub=stub)
    assert stub.calls == []


@pytest.mark.asyncio
async def test_low_confidence_gender_is_not_recorded(monkeypatch):
    stub = _LeadGenderStub(stored="")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="female", gender_confidence=0.5),
        gender_stub=stub)
    assert stub.calls == []


@pytest.mark.asyncio
async def test_degraded_turn_never_records_gender(monkeypatch):
    stub = _LeadGenderStub(stored="")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="female", gender_confidence=0.9, degraded=True),
        gender_stub=stub)
    assert stub.calls == []


@pytest.mark.asyncio
async def test_stored_gender_is_not_overwritten_by_a_bare_inference(monkeypatch):
    stub = _LeadGenderStub(stored="male")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="female", gender_confidence=0.95, gender_stated=False),
        gender_stub=stub)
    assert stub.calls == [
        {"chat_id": "z1", "gender": "female", "contact_id": None, "override": False}
    ]
    assert stub.stored == "male"


@pytest.mark.asyncio
async def test_stated_self_reference_overrides_stored_gender(monkeypatch):
    stub = _LeadGenderStub(stored="male")
    result, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="female", gender_confidence=0.95, gender_stated=True),
        gender_stub=stub)
    assert stub.calls == [
        {"chat_id": "z1", "gender": "female", "contact_id": None, "override": True}
    ]
    assert stub.stored == "female"
    # The resolved address form reaches the reply, not the neutral token.
    assert "chị" in result["reply"].lower()
    assert "anh/chị" not in result["reply"].lower()


@pytest.mark.asyncio
async def test_stored_gender_lookup_failure_keeps_turn_working(monkeypatch):
    stub = _LeadGenderStub(raises=True)
    result, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="unknown"),
        gender_stub=stub)
    assert result["outcome"] == "sent"
    assert stub.calls == []


@pytest.mark.asyncio
async def test_messenger_conv_passes_contact_id_to_gender_port(monkeypatch):
    conv = _FakeConv(zalo_chat_id=None, zalo_channel="facebook_messenger", contact_id="ct-9")
    stub = _LeadGenderStub(stored="")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="female", gender_confidence=0.9),
        gender_stub=stub,
        conv=conv)
    assert stub.calls[0]["contact_id"] == "ct-9"


# ---------------------------------------------------------------------------
# Candidate profile-name capture (Jev judgment -> blank lead.name)
# ---------------------------------------------------------------------------


class _ProfileNameGenderStub(_LeadGenderStub):
    """Gender stub that also records Jev-validated profile-name writes."""

    def __init__(self, *args, stored_name: str | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stored_name = stored_name
        self.name_calls: list[dict] = []

    async def record_profile_name(
        self,
        chat_id: str,
        name: str,
        *,
        contact_id: str | None = None,
        lead: dict | None = None) -> bool:
        self.name_calls.append({"chat_id": chat_id, "name": name, "contact_id": contact_id})
        if self.stored_name:
            return False
        self.stored_name = name
        return True


@pytest.mark.asyncio
async def test_jev_validated_profile_name_is_recorded_on_blank_lead(monkeypatch):
    stub = _ProfileNameGenderStub(stored="")
    result, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(profile_name_is_name=True),
        gender_stub=stub,
        state=_state_with_user_name("Duc Huy Nguyen"))
    assert result["outcome"] == "sent"
    assert stub.name_calls == [
        {"chat_id": "z1", "name": "Duc Huy Nguyen", "contact_id": None}
    ]


@pytest.mark.asyncio
async def test_jev_rejected_profile_name_is_not_recorded(monkeypatch):
    stub = _ProfileNameGenderStub(stored="")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(profile_name_is_name=False),
        gender_stub=stub,
        state=_state_with_user_name("Bé Gấu Shop"))
    assert stub.name_calls == []


@pytest.mark.asyncio
async def test_degraded_jev_never_records_profile_name(monkeypatch):
    stub = _ProfileNameGenderStub(stored="")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(profile_name_is_name=True, degraded=True),
        gender_stub=stub,
        state=_state_with_user_name("Duc Huy Nguyen"))
    assert stub.name_calls == []


@pytest.mark.asyncio
async def test_blank_profile_name_is_never_recorded(monkeypatch):
    stub = _ProfileNameGenderStub(stored="")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(profile_name_is_name=True),
        gender_stub=stub,
        state=_state_with_user_name("   "))
    assert stub.name_calls == []


@pytest.mark.asyncio
async def test_existing_lead_name_blocks_profile_name_write(monkeypatch):
    stub = _ProfileNameGenderStub(stored="", stored_name="Nguyễn Văn A")
    _, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(profile_name_is_name=True),
        gender_stub=stub,
        state=_state_with_user_name("Duc Huy Nguyen"))
    assert stub.name_calls != []
    assert stub.stored_name == "Nguyễn Văn A"


@pytest.mark.asyncio
async def test_gender_stub_without_name_method_keeps_turn_working(monkeypatch):
    """Old double stubs without record_profile_name must not break the turn."""
    stub = _LeadGenderStub(stored="")
    result, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(profile_name_is_name=True),
        gender_stub=stub,
        state=_state_with_user_name("Duc Huy Nguyen"))
    assert result["outcome"] == "sent"


@pytest.mark.asyncio
async def test_profile_name_from_state_user_name(monkeypatch):
    state = BotRunState(
        conversation_id=CONV_ID,
        version_at_start=1,
        user_text="tôi muốn tìm việc lái xe",
        user_name="Nguyễn Thị Hoa")
    _, deps = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="unknown"),
        gender_stub=_LeadGenderStub(),
        state=state)
    assert deps.turn_decisions.calls[0]["profile_name"] == "Nguyễn Thị Hoa"


@pytest.mark.asyncio
async def test_profile_name_falls_back_to_contact_display_name(monkeypatch):
    conv = _FakeConv()
    conv.contact = SimpleNamespace(display_name="Trần Văn Hùng")
    _, deps = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="unknown"),
        gender_stub=_LeadGenderStub(),
        conv=conv)
    assert deps.turn_decisions.calls[0]["profile_name"] == "Trần Văn Hùng"


class _ResolvingLeadGenderStub:
    """The real adapter's seam: one resolve_lead, every call reuses the row."""

    def __init__(self, lead: dict | None) -> None:
        self.lead = lead
        self.resolutions = 0
        self.reads: list[dict | None] = []
        self.writes: list[dict] = []

    async def resolve_lead(self, chat_id: str, contact_id: str | None = None):  # noqa: ARG002
        self.resolutions += 1
        return self.lead

    async def stored_gender(
        self, chat_id: str, contact_id: str | None = None, *, lead=None
    ) -> str:
        self.reads.append(lead)
        return str((lead or {}).get("gender") or "").strip().lower()

    async def record_inferred_gender(
        self, chat_id, gender, *, contact_id=None, override=False, lead=None
    ):  # noqa: ARG001
        self.writes.append({"gender": gender, "override": override, "lead": lead})
        return True


@pytest.mark.asyncio
async def test_lead_row_resolved_once_and_reused_across_calls(monkeypatch):
    """A port exposing the resolve seam is asked for the lead exactly once per
    turn; the stored read and the inference write receive the same row."""
    lead = {"id": 5, "zalo_id": "z1", "gender": ""}
    stub = _ResolvingLeadGenderStub(lead)
    result, _ = await _run_gender_turn(
        monkeypatch,
        decisions=TurnDecisions(gender="female", gender_confidence=0.9),
        gender_stub=stub)
    assert result["outcome"] == "sent"
    assert stub.resolutions == 1
    assert stub.reads == [lead]
    assert stub.writes == [{"gender": "female", "override": False, "lead": lead}]


@pytest.mark.asyncio
async def test_agent_turn_passes_the_resolved_lead_row_to_context(monkeypatch):
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _FakeLead:
        async def context(
            self, chat_id, current_user_text, recent_messages, contact_id=None, lead=None
        ):  # noqa: ARG001
            captured["lead"] = lead
            return "", ""

        def instruction(self, question):  # noqa: ARG001
            return ""

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG001
            return "Dạ em chào anh ạ."

    monkeypatch.setattr(
        "app.graph.context.build_system_prompt", _fake_build_system_prompt
    )
    monkeypatch.setattr(runner, "build_agent_user_text", lambda **kw: kw["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    lead_row = {"id": 5, "zalo_id": "z1", "gender": "female"}
    await _agent_turn(
        _state(),
        deps,
        "chào bạn",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        decisions=TurnDecisions(degraded=True),
        lead_row=lead_row)

    assert captured["lead"] is lead_row


@pytest.mark.asyncio
async def test_jev_decision_overlaps_the_pending_write(monkeypatch):
    """The Jev HTTP call starts while the pending write is still in flight —
    its latency hides behind the preamble DB work instead of serialising
    after it (the turn's wall-clock drops by the overlap)."""
    conv = _FakeConv()
    timeline: dict[str, float] = {}

    class _Svc:
        async def get(self, _id):
            return conv

        async def last_messages(self, c, limit):  # noqa: ARG001
            return []

        async def record_bot_pending(self, c, **_kwargs):
            timeline["pending_started"] = time.monotonic()
            await asyncio.sleep(0.05)
            timeline["pending_ended"] = time.monotonic()
            return SimpleNamespace(id=777)

        async def recheck_ownership(self, c, version_at_start, lock_owner=None):  # noqa: ARG001
            return True

        async def claim_send(
            self, c, *, version_at_start, lock_owner, pending_message_id, reply, **_kwargs
        ):  # noqa: ARG001
            return pending_message_id is not None

        async def record_bot_outcome(self, c, **kw):  # noqa: ARG002
            return None

    class _Port:
        async def decide_turn(self, **kwargs):  # noqa: ARG002
            timeline["jev_started"] = time.monotonic()
            await asyncio.sleep(0.01)
            return TurnDecisions(degraded=True)

    _stub_agent(monkeypatch, "Dạ em chào anh ạ.")
    deps = _deps(_FakeZalo(), conversation=_Svc())
    deps.turn_decisions = _Port()

    res = await run_turn(_state(), deps)

    assert res["outcome"] == "sent"
    assert timeline["jev_started"] < timeline["pending_ended"]


# ─── silent terminals never leave the placeholder row behind ────────────────
#
# "Đang soạn trả lời..." is persisted before the answer exists, so every path
# that ends the turn without sending must resolve THAT row — the candidate must
# never be left with a bubble that never resolves. These tests run the real
# ``ConversationState.record_bot_outcome`` resolution against a live Message row
# so the assertion is the row's end state, not the call wiring.

_PLACEHOLDER_BODY = "Đang soạn trả lời..."


class _PlaceholderSession:
    """Minimal session stand-in that owns one live BOT/PENDING row."""

    def __init__(self, row) -> None:
        self.row = row
        self.added: list = []

    async def get(self, _model, ident, **_kwargs):
        return self.row if ident == self.row.id else None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if hasattr(obj, "proposed_reply") and getattr(obj, "id", None) is None:
                obj.id = 99

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj, attribute_names=None) -> None:  # noqa: ARG001
        return None

    async def execute(self, *_args, **_kwargs):
        return SimpleNamespace(rowcount=0)

    async def rollback(self) -> None:
        return None


def _pending_row(conv, *, message_id: int = 42):
    from app.models.conversation import DeliveryStatus, Message, MessageSender

    row = Message(
        conversation_id=conv.id,
        sender=MessageSender.BOT,
        body=_PLACEHOLDER_BODY,
        delivery_status=DeliveryStatus.PENDING)
    row.id = message_id
    return row


def _pending_row_svc(*, conv, row, owned: bool = True):
    """A ConversationPort stub whose record_bot_outcome is the real resolution."""
    from unittest.mock import MagicMock

    from app.services.conversation.state import ConversationState

    db = _PlaceholderSession(row)
    state = ConversationState(db, MagicMock(), AsyncMock())

    class _Svc:
        async def get(self, _id):
            return conv

        async def last_messages(self, c, limit):
            return []

        async def record_bot_pending(self, c, **_kwargs):
            return row

        async def recheck_ownership(self, c, version_at_start, lock_owner=None):
            return owned

        async def claim_send(
            self, c, *, version_at_start, lock_owner, pending_message_id, reply, **_kwargs
        ):
            return owned and pending_message_id is not None

        async def record_bot_outcome(self, c, **kwargs):
            return await state.record_bot_outcome(c, **kwargs)

    return _Svc(), db, row


def _added_messages(db) -> list:
    from app.models.conversation import Message

    return [obj for obj in db.added if isinstance(obj, Message)]


async def _run_silent_turn(monkeypatch, *, owned: bool, agent) -> tuple[dict, object, object]:
    from app.models.conversation import DeliveryStatus

    conv = _FakeConv()
    conv.id = uuid.UUID(CONV_ID)
    conv.conversation_seq = 1
    row = _pending_row(conv)
    svc, db, row = _pending_row_svc(conv=conv, row=row, owned=owned)
    _stub_agent(monkeypatch, agent)
    result = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, db=db))
    assert row.delivery_status == DeliveryStatus.SUPPRESSED, (
        "a silent terminal must resolve the placeholder to a terminal status"
    )
    assert row.body != _PLACEHOLDER_BODY
    assert _added_messages(db) == [], "the placeholder is resolved in place, never duplicated"
    return result, row, db


@pytest.mark.asyncio
async def test_claim_failure_suppression_resolves_the_placeholder_row(monkeypatch):
    """A newer inbound (or takeover) bumped the version: the claim loses and the
    drafted answer is never sent — the placeholder row must still resolve."""
    result, row, _ = await _run_silent_turn(
        monkeypatch, owned=False, agent="Dạ em chào anh/chị ạ"
    )

    assert result["outcome"] == "suppressed"
    assert row.body == "Dạ em chào anh/chị ạ"  # the drafted answer is kept for audit


@pytest.mark.asyncio
async def test_agent_error_suppression_resolves_the_placeholder_row(monkeypatch):
    result, row, _ = await _run_silent_turn(
        monkeypatch, owned=True, agent=ValueError("agent blew up")
    )

    assert result["outcome"] == "error"
    assert row.body == ""  # nothing was sent — no invented text


@pytest.mark.asyncio
async def test_empty_reply_suppression_resolves_the_placeholder_row(monkeypatch):
    result, row, _ = await _run_silent_turn(monkeypatch, owned=True, agent="   ")

    assert result["outcome"] == "suppressed"
    assert row.body == ""


# ---------------------------------------------------------------------------
# Progressive send (opt-in early bubble)
# ---------------------------------------------------------------------------

# A realistic multi-part answer: the first sentence-aligned bubble forms at the
# third sentence, leaving two sentences for the normal remainder path.
_ANSWER_SENTENCES = [
    "Về thu nhập, lương cơ bản của công nhân là 6 triệu đồng mỗi tháng, cộng phụ cấp chuyên cần. ",
    "Về ca làm việc, bạn có thể chọn ca ngày hoặc ca đêm luân phiên theo tuần làm việc. ",
    "Về ký túc xá, công ty hỗ trợ chỗ ở miễn phí cho công nhân ở xa, có cả xe đưa đón. ",
    "Về hồ sơ, bạn cần chuẩn bị chứng minh nhân dân và sổ hộ khẩu khi nhận việc. ",
    "Về thời gian, ca làm việc kéo dài 8 tiếng và có tăng ca nếu bạn muốn thêm thu nhập. ",
]
_ANSWER = "".join(_ANSWER_SENTENCES)

# Filler-only opening: clears the character floor but carries no concrete signal,
# so the gate must not forward it.
_PLEASANTRY = "Dạ em chào anh/chị ạ. "


def _norm(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.asyncio
async def test_progressive_flag_off_keeps_the_single_message_path(monkeypatch):
    """Flag off: one send, one outcome row, one claim — nothing progressive runs."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv)
    _stub_agent(monkeypatch, "Chào bạn!")
    zalo = _FakeZalo()

    res = await run_turn(_state(), _deps(zalo, conversation=svc, progressive_send=False))

    assert res == {"outcome": "sent", "reply": "Chào bạn!"}
    assert zalo.sent == [("z1", "Chào bạn!")]
    assert len(recorded) == 1
    assert len(svc.claims) == 1
    assert svc.claims[0]["pending_message_id"] == 777
    assert svc.claims[0]["outbox_payload"]["text"] == "Chào bạn!"
    stage = recorded[0]["stage_timings"]
    assert "progressive_send" not in stage
    assert "first_bubble_ms" not in stage


@pytest.mark.asyncio
async def test_progressive_long_answer_sends_first_bubble_before_the_agent_returns(monkeypatch):
    """Long streamed answer: the first bubble goes out mid-generation, the
    remainder follows the normal path, and the turn writes exactly one BotRun."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    zalo = _FakeZalo()
    _stub_streaming_agent(monkeypatch, _ANSWER_SENTENCES, svc=svc, pause_after=2)
    offset = runner._next_sendable_offset(_ANSWER)

    res = await run_turn(_state(), _deps(zalo, conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    # Exactly two candidate-visible messages: the early bubble and the remainder.
    assert len(svc.dispatched) == 2
    bubble = svc.dispatched[0]["text"]
    remainder = svc.dispatched[1]["text"]
    assert bubble == _ANSWER[:offset]
    assert remainder == _ANSWER[offset:]
    # Nothing lost at the join (the boundary consumes one space) and nothing sent
    # twice: each part occurs exactly once in the answer.
    assert _norm(f"{bubble} {remainder}") == _norm(_ANSWER)
    assert _ANSWER.count(bubble) == 1
    assert _ANSWER.count(remainder) == 1
    # The agent was still running when the first message was already dispatched.
    assert svc.agent_returned_after_dispatches == [1]
    # One BotRun for the turn, written against the remainder's row.
    assert len(recorded) == 1
    assert recorded[0]["reply"] == _ANSWER[offset:]
    assert recorded[0]["sent"] is True
    stage = recorded[0]["stage_timings"]
    assert stage["progressive_send"] is True
    assert stage["progressive_bubbles"] == 2
    assert stage["first_bubble_ms"] >= 0
    assert "total_ms" in stage and "send_ms" in stage and stage["lane"] == "agent"
    # The early bubble was claimed on the ORIGINAL placeholder and terminalized
    # through the durable outbox seam; the remainder got a NEW placeholder.
    assert svc.claims[0]["pending_message_id"] == 777
    assert svc.claims[0]["outbox_payload"]["text"] == _ANSWER[:offset]
    assert svc.claims[1]["pending_message_id"] == 778
    assert len(svc.pending_bodies) == 2
    assert svc.finalized and svc.finalized[0]["message_id"] == 777
    assert svc.finalized[0]["outbox_id"] == 777
    assert svc.finalized[0]["delivered"] is True
    assert svc.finalized[0]["telemetry"] is None  # no recovery BotRun


@pytest.mark.asyncio
async def test_progressive_short_answer_sends_one_message(monkeypatch):
    """Short answer: the lane wins the race, so delivery is unchanged."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    _stub_streaming_agent(monkeypatch, ["Dạ em chào anh/chị ạ. Em kiểm tra ngay ạ."], svc=svc)

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    assert len(svc.dispatched) == 1
    assert svc.dispatched[0]["text"] == "Dạ em chào anh/chị ạ. Em kiểm tra ngay ạ."
    assert len(recorded) == 1
    assert len(svc.claims) == 1
    assert "progressive_send" not in recorded[0]["stage_timings"]


@pytest.mark.asyncio
async def test_progressive_claim_loss_sends_nothing(monkeypatch):
    """Early claim lost (takeover / newer inbound): no partial message goes out."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True, owned=False)
    _stub_streaming_agent(
        monkeypatch,
        _ANSWER_SENTENCES,
        svc=svc,
        pause_after=2,
        pause_event=svc.claim_attempted,
    )

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "suppressed"
    assert svc.dispatched == []
    assert len(recorded) == 1
    assert recorded[0]["sent"] is False
    # The finalized whole reply is kept for audit — nothing was sent.
    assert recorded[0]["reply"] == _ANSWER
    assert "progressive_send" not in recorded[0]["stage_timings"]


@pytest.mark.asyncio
async def test_progressive_empty_remainder_records_one_bot_run(monkeypatch):
    """The bubble IS the whole answer: one message, one BotRun, no extra row."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    parts = _ANSWER_SENTENCES[:3]  # ends exactly at the bubble boundary
    _stub_streaming_agent(monkeypatch, parts, svc=svc, pause_after=2)
    raw = "".join(parts)
    offset = runner._next_sendable_offset(raw)

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    assert len(svc.dispatched) == 1
    assert svc.dispatched[0]["text"] == raw[:offset]
    assert len(recorded) == 1
    assert recorded[0]["sent"] is True
    assert recorded[0]["reply"] == raw[:offset]
    assert recorded[0]["pending_message_id"] == 777
    assert svc.finalized == []  # nothing to terminalize separately
    assert len(svc.pending_bodies) == 1  # no second placeholder
    stage = recorded[0]["stage_timings"]
    assert stage["progressive_send"] is True
    assert stage["progressive_bubbles"] == 1


@pytest.mark.asyncio
async def test_progressive_pleasantry_opening_waits_for_the_first_useful_boundary(monkeypatch):
    """A pleasantry-only opening that clears the floor is not sent: the bubble
    moves to the next boundary, where the answer has substance."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    parts = [_PLEASANTRY] * 12 + [_ANSWER_SENTENCES[0], _ANSWER_SENTENCES[1]]
    _stub_streaming_agent(monkeypatch, parts, svc=svc, pause_after=12)
    raw = "".join(parts)
    filler_offset = runner._next_sendable_offset(raw)
    useful_offset = runner._next_sendable_offset(raw, min_offset=filler_offset + 1)
    assert not runner._bubble_has_substance(raw[:filler_offset])
    assert runner._bubble_has_substance(raw[:useful_offset])

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    assert len(svc.dispatched) == 2
    assert svc.dispatched[0]["text"] == raw[:useful_offset]
    assert svc.dispatched[1]["text"] == raw[useful_offset:]
    # The send waited for substance, so it was not "skipped for lack of" it.
    assert "progressive_first_bubble_skipped" not in recorded[0]["stage_timings"]


@pytest.mark.asyncio
async def test_progressive_short_greeting_answer_never_sends_early(monkeypatch):
    """A short greeting-only answer never reaches the floor: one message, no
    progressive telemetry at all."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    parts = [_PLEASANTRY] * 4  # 88 chars — well under the floor
    _stub_streaming_agent(monkeypatch, parts, svc=svc)
    raw = "".join(parts)
    assert runner._next_sendable_offset(raw) is None

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    assert len(svc.dispatched) == 1
    assert svc.dispatched[0]["text"] == raw
    stage = recorded[0]["stage_timings"]
    assert "progressive_send" not in stage
    assert "progressive_first_bubble_skipped" not in stage


@pytest.mark.asyncio
async def test_progressive_pleasantry_only_answer_never_sends_early(monkeypatch):
    """A floor-clearing pleasantry-only answer is never forwarded early, and the
    skip reason is stamped for the dashboard."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    parts = [_PLEASANTRY] * 24  # 528 chars of filler, boundaries but no substance
    _stub_streaming_agent(monkeypatch, parts, svc=svc)
    raw = "".join(parts)
    assert runner._next_sendable_offset(raw) is not None
    assert not runner._bubble_has_substance(raw)

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    assert len(svc.dispatched) == 1
    assert svc.dispatched[0]["text"] == raw
    stage = recorded[0]["stage_timings"]
    assert stage["progressive_first_bubble_skipped"] == "no_substance"
    assert "progressive_send" not in stage


@pytest.mark.asyncio
async def test_progressive_wait_cap_falls_back_to_the_whole_reply(monkeypatch):
    """Past the wait cap the sender stops trying: the complete answer goes out as
    a single message."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    parts = ["x" * 300 + ". " + "y" * 500 + ". ", "z" * 120 + ". "]
    _stub_streaming_agent(monkeypatch, parts, svc=svc)
    raw = "".join(parts)
    assert len(raw) > runner.PROGRESSIVE_MAX_WAIT_CHARS

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    assert len(svc.dispatched) == 1
    assert svc.dispatched[0]["text"] == raw
    stage = recorded[0]["stage_timings"]
    assert "progressive_send" not in stage
    assert "progressive_first_bubble_skipped" not in stage


@pytest.mark.asyncio
async def test_progressive_inline_thinking_answer_sends_bubble_from_visible_text(monkeypatch):
    """MiniMax M2 streams its deliberation inline in think tags before the
    answer. The wait cap, the bubble floor and the boundary search must all be
    measured against the candidate-visible text, so the bubble still goes out
    while the agent is generating — and the deliberation never leaves."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    reasoning = "Người dùng hỏi về LG Display. " * 30
    parts = [
        "\u003cthink\u003e" + reasoning + "\u003c/think\u003e",
        _ANSWER_SENTENCES[0],
        _ANSWER_SENTENCES[1],
        _ANSWER_SENTENCES[2],
        _ANSWER_SENTENCES[3],
        _ANSWER_SENTENCES[4],
    ]
    assert len(reasoning) > runner.PROGRESSIVE_MAX_WAIT_CHARS
    _stub_streaming_agent(monkeypatch, parts, svc=svc, pause_after=len(parts) - 1)

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    assert len(svc.dispatched) == 2
    bubble = svc.dispatched[0]["text"]
    remainder = svc.dispatched[1]["text"]
    # The bubble is the visible answer, never the deliberation.
    assert "Người dùng hỏi" not in bubble
    assert "think" not in bubble
    assert _ANSWER.startswith(bubble)
    assert bubble.rstrip().endswith((".", "!", "?", "…"))
    # The split is lossless at the sentence boundary (which consumes one space).
    assert _norm(f"{bubble} {remainder}") == _norm(_ANSWER)
    # The send happened while the agent was still generating.
    assert svc.agent_returned_after_dispatches == [1]
    assert recorded[0]["reply"] == remainder
    stage = recorded[0]["stage_timings"]
    assert stage["progressive_send"] is True
    assert stage["progressive_bubbles"] == 2

