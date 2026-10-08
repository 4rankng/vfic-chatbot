# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportTypedDictNotRequiredAccess=false, reportOptionalSubscript=false, reportOptionalMemberAccess=false, reportReturnType=false, reportOptionalOperand=false, reportOptionalCall=false, reportOperatorIssue=false, reportIndexIssue=false
#
# Typed-double convention (mirrors test_integration_settings.py, issue #39
# option b): the stubs in this file (_FakeAgent, _FakeDB, _Conversations,
# _FakeZalo, _Svc, …) deliberately implement only the narrow duck-typed surface
# run_turn exercises, so every construction and GraphDeps assignment trips
# reportArgumentType/reportAttributeAccessIssue, the outcome assertions index
# TurnOutcome's optional keys (reportTypedDictNotRequiredAccess), and the
# optional-flow/single-hit rules fire on assertion lines. Casting the ~130
# sites would add noise, not safety — the real gate is the behavioral suite
# below.
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

from app.graph import lanes, runner
from app.graph.direct_context import DirectContext, ProjectTurnContext
from app.graph.llm_semaphore import LLMThrottled
from app.graph.ports import TurnDecisions
from app.graph.runner import run_turn
from app.graph.types import BotRunState, GraphDeps
from app.graph.tingting_guide import tingting_hotline_reply

# The owner-approved escalation hotline (the value Alembic 0058 seeds). The
# builders take the number explicitly, so tests pass it instead of any
# module-level copy existing in production code.
TINGTING_HOTLINE_REPLY = tingting_hotline_reply("+84 914 827 988")

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
        contact_id=None,
        id=None) -> None:
        # The persist job carries the conversation's primary key: the Messenger
        # lead write is contact-keyed, so the job cannot be resolved by chat id.
        self.id = id if id is not None else uuid.uuid4()
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
async def test_project_detail_turn_folds_direct_context_into_the_agent():
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

    captured: dict[str, object] = {}

    class _DirectAgent:
        calls = 0

        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            self.calls += 1
            captured["system"] = kwargs.get("system", "")
            captured["resolved_tool_registry"] = kwargs.get("resolved_tool_registry")
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

    assert result == {
        "outcome": "sent",
        "reply": "LG Display Hải Phòng tuyển công nhân thời vụ.",
    }
    assert direct_agent.calls == 1
    # The retired direct lane rides inside the agent lane now: the KB full text
    # is in the prompt and no tools are bound (a tool cannot add evidence).
    assert "KIẾN THỨC DỰ ÁN (toàn văn, nguồn chính thức)" in captured["system"]
    assert captured["resolved_tool_registry"] == frozenset()


@pytest.mark.asyncio
@pytest.mark.parametrize("rewrite_completes", [True, False])
async def test_direct_context_uses_the_same_bounded_completion_and_delivery_guard(rewrite_completes):
    from app.graph.clients import MiniMaxAgent
    from langchain_core.messages import AIMessage

    knowledge = "Rorze tuyển nhân viên lắp ráp tại Hải Phòng. Lương cơ bản 6 triệu đồng/tháng."
    complete = "Dạ Rorze tuyển nhân viên lắp ráp tại Hải Phòng, lương cơ bản 6 triệu đồng/tháng ạ."

    class Reader:
        async def active_context(self):
            return DirectContext(
                knowledge_base_id="kb-rorze", persona_body="Bạn là tư vấn viên.",
                knowledge_text=knowledge,
            )

    class Model:
        def __init__(self):
            self.calls = 0
            self.system = ""

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            self.system = str(messages[0].content)
            return AIMessage(
                content=complete if self.calls == 4 and rewrite_completes else "Thông tin dự án chưa hoàn",
                response_metadata={"finish_reason": "stop" if self.calls == 4 and rewrite_completes else "length"},
            )

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    deps = _deps(_FakeZalo(), conversation=svc)
    model = Model()
    deps.agent = MiniMaxAgent(model, embedder=None, max_iters=1)
    deps.direct_context = Reader()

    result = await run_turn(BotRunState(
        conversation_id=CONV_ID, version_at_start=1,
        user_text="Công việc ở Rorze là gì?",
    ), deps)

    assert model.calls == 4
    assert knowledge in model.system
    if rewrite_completes:
        assert result == {"outcome": "sent", "reply": complete}
        assert svc.dispatched[0]["text"] == complete
        assert recorded[0]["reply"] == complete
    else:
        assert result["outcome"] == "suppressed"
        assert svc.dispatched == []
        assert recorded[0]["stage_timings"]["answer_completion_failure"] == "output_cap_exhausted"


@pytest.mark.asyncio
async def test_direct_context_strips_minimax_reasoning_before_delivery():
    class _DirectReader:
        async def active_context(self):
            return DirectContext(
                knowledge_base_id="kb-rorze",
                persona_body="Bạn là tư vấn viên.",
                knowledge_text="Rorze đang tuyển nhân viên lắp ráp và vận hành máy CNC.")

    class _DirectAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
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
    assert result == {"outcome": "sent", "reply": visible_reply}
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
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
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
async def test_project_clarification_is_an_agent_instruction_not_a_canned_reply():
    class _ProjectReader:
        async def resolve(self, conv, user_text):  # noqa: ARG002
            return ProjectTurnContext(
                state="EXPLORE",
                clarification=(
                    "<think>internal routing note</think>"
                    "Bạn muốn hỏi Rorze hay LG Display?"
                ),
                clarification_projects=("Rorze", "LG Display"))

    captured: dict[str, object] = {}

    class _Agent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            return "Bạn muốn hỏi Rorze hay LG Display?"

    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv)
    zalo = _FakeZalo()
    deps = _deps(zalo, conversation=svc)
    deps.agent = _Agent()
    deps.direct_context = _ProjectReader()

    result = await run_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="Rorze ở đâu?"),
        deps)

    visible_reply = "Bạn muốn hỏi Rorze hay LG Display?"
    assert result == {"outcome": "sent", "reply": visible_reply}
    assert zalo.sent == [("z1", visible_reply)]
    assert recorded[-1]["reply"] == visible_reply
    # The retired clarification lane's string is now a mandatory instruction
    # carried by the route hint; the agent authors the question.
    assert "PHẢI hỏi lại ứng viên muốn hỏi dự án nào" in captured["user_text"]
    assert "Rorze, LG Display" in captured["user_text"]


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

        async def agent(self, user_text, **kwargs):  # noqa: ARG002
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
        "outcome": "sent",
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

        async def agent(self, user_text, **kwargs):  # noqa: ARG002
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

    assert result["outcome"] == "sent"
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
            "contact_id": None,
            "conversation_id": str(conv.id),
        }
    ]


@pytest.mark.asyncio
async def test_direct_vacancy_question_reaches_agent(monkeypatch):
    user_text = "bên bạn có nhận thợ hàn không?"

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
    deps = _deps(zalo, conversation=svc)
    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text)

    result = await run_turn(state, deps)

    assert result["outcome"] == "sent"
    assert result["reply"] == f"LLM saw: {user_text}"
    assert captured["user_text"] == user_text
    assert captured["chat_id"] == "z1"
    assert recorded[0]["stage_timings"]["lane"] == "agent"


@pytest.mark.parametrize(
    "user_text",
    [
        "giới thiệu các vị trí đang tuyển",
        "hiện tại có những công việc gì đang tuyển",
        "LG tuyển thợ hàn không?",
    ])
@pytest.mark.asyncio
async def test_vacancy_prompts_reach_agent(monkeypatch, user_text):
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
    deps = _deps(zalo, conversation=svc)
    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text)

    result = await run_turn(state, deps)

    assert result["outcome"] == "sent"
    assert result["reply"] == f"LLM saw: {user_text}"
    assert captured["user_text"] == user_text
    assert captured["chat_id"] == "z1"
    assert recorded[0]["stage_timings"]["lane"] == "agent"


@pytest.mark.asyncio
async def test_vacancy_followup_reaches_agent_with_scoped_query(monkeypatch):
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
    deps = _deps(zalo, conversation=svc)
    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="lương bao nhiêu?")

    result = await run_turn(state, deps)

    assert result["outcome"] == "sent"
    assert result["reply"] == "LLM saw follow-up: lương bao nhiêu?"
    assert captured["user_text"] == "lương bao nhiêu?"
    assert captured["recent_messages"][0].body == "bên bạn tuyển thợ hàn CO2 đúng ko?"
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
async def test_stray_code_fence_ships_without_markdown_decorations(monkeypatch):
    """A stray code fence ships as plain prose: decorations stripped, text kept.

    The operator rule is that candidates read plain text — the old verbatim
    fence policy predates the markdown-stripping boundary.
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
    assert res["reply"] == "Bạn cần mang CCCD. print(1) Hẹn gặp lúc 8h nhé."
    assert zalo.sent[0][1] == res["reply"]


# ---------------------------------------------------------------------------
# No hard cap on the agent (advisory deadline only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_runs_to_completion_past_deadline(monkeypatch):
    """No hard cap: an agent that outlasts the propagated deadline is NOT cancelled
    — its real reply is sent. Cancelling live LLM calls mid-generation produced
    excessive TIMEOUT fallbacks in prod, so the deadline is advisory (it bounds
    the pre-agent lookups only) and never kills the agent turn."""
    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)

    async def _slow_agent(
        state, deps, user_text, *, provider=None, chat_id, recent_messages, contact_id=None, timings=None, decisions=None
    ):  # noqa: ARG001
        await asyncio.sleep(0.3)  # far past any wall-clock the turn used to allow
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
async def test_typing_heartbeat_survives_provider_failures():
    """The heartbeat is best-effort: a provider rejecting the typing pulse is
    swallowed and the cadence continues — a flapping channel must never break
    a turn (the caller cancels the task before every real send)."""

    class _RaisingZalo:
        def __init__(self) -> None:
            self.attempts = 0

        async def send_chat_action(self, chat_id: str, action: str) -> None:
            self.attempts += 1
            raise RuntimeError("provider down")

    zalo = _RaisingZalo()
    settings = SimpleNamespace(typing_heartbeat_seconds=3.5)
    task = asyncio.create_task(runner._status_heartbeat(zalo, "chat-1", settings=settings))
    await asyncio.sleep(0.05)  # first pulse fires immediately (next_typing = 0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # the cancel is the expected end; the swallow is what is pinned
    assert zalo.attempts == 1


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
    assert res["reply"] == long_reply
    assert zalo.sent == [("z1", long_reply)]


@pytest.mark.parametrize("provider", ["bot", "oa", "facebook_messenger"])
@pytest.mark.asyncio
async def test_all_five_projects_reach_the_claim_delivery_and_receipt(monkeypatch, provider):
    """A complete model list cannot lose projects at the shared send boundary."""
    names = ("LG Display", "Rorze", "Amtran", "Kyocera", "Pegatron")
    reply = "Dạ em gửi đủ 5 dự án đang tuyển để anh/chị dễ chọn ạ:\n\n" + "\n\n".join(
        f"{index}. {name}: tại Hải Phòng. Thu nhập 8-12 triệu/tháng theo dữ liệu dự án. "
        "Phạm vi công việc gồm sản xuất, kiểm tra chất lượng và lắp ráp sản phẩm."
        for index, name in enumerate(names, 1)
    ) + "\n\nAnh/chị quan tâm dự án nào để em tư vấn tiếp ạ?"
    assert len(reply) > 450
    identity = (
        SimpleNamespace(provider=provider, external_id="psid-1", account_key="page-1")
        if provider == "facebook_messenger" else None
    )
    conv = _FakeConv(zalo_channel=provider, channel_identity=identity)
    svc, recorded = _stub_svc(conv=conv, durable=True)
    _stub_agent(monkeypatch, reply)
    state = _state()
    state.user_text = "Cho tôi xem tất cả dự án đang tuyển"

    result = await run_turn(state, _deps(_FakeZalo(), conversation=svc))

    assert result == {"outcome": "sent", "reply": reply}
    assert svc.claims[0]["reply"] == reply
    assert svc.claims[0]["outbox_payload"]["text"] == reply
    assert svc.dispatched[0]["text"] == reply
    assert recorded[0]["reply"] == reply
    for name in names:
        assert recorded[0]["reply"].count(name) == 1


@pytest.mark.asyncio
async def test_progressive_large_first_bubble_and_remainder_preserve_every_project(monkeypatch):
    """A raw prefix offset must never advance past text removed from the bubble."""
    names = ("LG Display", "Rorze", "Amtran", "Kyocera", "Pegatron")
    first = "LG Display: " + "Thông tin công việc và quyền lợi đã được xác minh " * 10 + ".\n"
    assert 450 < len(first) < runner.PROGRESSIVE_MAX_WAIT_CHARS
    parts = [first] + [f"{name}: công việc sản xuất tại Hải Phòng.\n" for name in names[1:]]
    raw = "".join(parts)
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    _stub_streaming_agent(monkeypatch, parts, svc=svc, pause_after=0)
    state = _state()
    state.user_text = "Cho tôi xem tất cả dự án đang tuyển"

    result = await run_turn(state, _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert result["outcome"] == "sent"
    assert len(svc.dispatched) == 2
    assert "".join(item["text"] for item in svc.dispatched) == raw
    offset = runner._next_sendable_offset(raw)
    assert svc.claims[0]["outbox_payload"]["text"] == raw[:offset]
    assert recorded[0]["reply"] == raw[offset:]
    assert svc.agent_returned_after_dispatches == [1]


@pytest.mark.asyncio
async def test_five_active_project_tool_evidence_survives_capped_generation_and_delivery(monkeypatch):
    """Run the actual catalog tool and completion guard through durable delivery."""
    from langchain_core.messages import AIMessage
    from app.graph.clients import MiniMaxAgent
    from app.recruitment.domain.recommendation import ProjectFeatures

    names = ("LG Display", "Rorze", "Amtran", "Kyocera", "Pegatron")
    complete = "Dạ đây là đủ 5 dự án đang tuyển ạ:\n\n" + "\n\n".join(
        f"{index}. {name}: tại Hải Phòng. Phạm vi công việc: sản xuất và kiểm tra chất lượng."
        for index, name in enumerate(names, 1)
    ) + "\n\nAnh/chị quan tâm dự án nào ạ?"
    cut_offset = complete.index("3. Amtran") + 4
    assert len(complete) > 450

    class Catalog:
        async def list_active_projects(self):
            return [
                ProjectFeatures(project_id=str(uuid.uuid4()), slug=f"project-{index}", name=name)
                for index, name in enumerate(names)
            ]

    class Model:
        def __init__(self):
            self.calls = 0
            self.catalog_evidence = ""

        def bind_tools(self, _schemas, **_kwargs):
            return self

        async def ainvoke(self, messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "list_active_projects", "args": {}, "id": "catalog",
                }])
            self.catalog_evidence = str(next(
                message.content for message in messages if message.type == "tool"
            ))
            return AIMessage(
                content=complete[:cut_offset] if self.calls == 2 else complete[cut_offset:],
                response_metadata={"finish_reason": "length" if self.calls == 2 else "stop"},
            )

    model = Model()
    agent = MiniMaxAgent(model, embedder=None, max_iters=2)

    async def catalog_agent(state, _deps, user_text, **kwargs):
        return await agent.agent(
            user_text,
            system="Chỉ trình bày các dự án từ dữ liệu công cụ.",
            retrieval=Catalog(),
            embedder=None,
            allowed_tools=("list_active_projects",),
            required_tool="list_active_projects",
            metrics=kwargs.get("timings"),
        )

    monkeypatch.setattr(runner, "_agent_turn", catalog_agent)
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    state = _state()
    state.user_text = "Cho tôi xem tất cả dự án đang tuyển"

    result = await run_turn(state, _deps(_FakeZalo(), conversation=svc))

    assert model.calls == 3  # catalog request, capped answer, bounded completion
    assert '"total":5' in model.catalog_evidence
    assert all(name in model.catalog_evidence for name in names)
    assert result == {"outcome": "sent", "reply": complete}
    assert svc.dispatched[0]["text"] == complete
    assert svc.claims[0]["outbox_payload"]["text"] == complete
    assert recorded[0]["reply"] == complete


# ---------------------------------------------------------------------------
# Adapter-error session safety: a swallowed adapter error must not poison the turn
# ---------------------------------------------------------------------------


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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kw: kw["current_user_text"])

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
        # safe_redirect is the only fast-eligible strategy, and a confident
        # off-domain turn now hands off before the model is ever reached. The
        # fast tier therefore serves the below-floor reading — the one that
        # still falls through to the agent — so that is the route pinned here.
        return TurnRoute("out_of_scope", "safe_redirect", reason="off_domain_terms", confidence=0.4)

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kw: kw["current_user_text"])
    monkeypatch.setattr(lanes, "route_from_decisions", _route_without_fast_tier)

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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

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
    assert captured["allowed_tools"] == ("list_active_projects",)
    assert captured["lookup_query"] == query
    assert captured["required_tool"] == "list_active_projects"
    assert captured["required_tool_args"] is None


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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])
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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

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
async def test_age_eligibility_question_requires_catalog_and_kb_search(monkeypatch):
    """An age question runs the checked catalog list, not a filler ask-back.

    Owner report 2026-10-08 ("60 tuổi có làm được không?"): each factory's age
    limit lives in its own KB and the catalog payload carries no age field, so
    with no tool authority the model answered a straight eligibility question
    by asking the candidate which project they meant. The gate now forces the
    catalog authority plus the KB search and overrides the route hint with the
    checked-list contract.
    """
    from app.graph.runner import _agent_turn

    captured: dict[str] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            captured["prompt"] = user_text
            return "Dạ các dự án nhận đủ 60 tuổi gồm..."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes,
        "build_agent_user_text",
        lambda **kwargs: f"{kwargs['current_user_text']}\n{kwargs.get('route_hint') or ''}",
    )

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    reply = await _agent_turn(
        BotRunState(
            conversation_id=CONV_ID, version_at_start=1, user_text="60 tuổi có làm được không?"
        ),
        deps,
        "60 tuổi có làm được không?",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        project_context=SimpleNamespace(
            state="EXPLORE", knowledge_mode=None, project_slug=None, project_name=None
        ),
        decisions=TurnDecisions(intent="general", intent_confidence=0.8),
    )

    assert reply.startswith("Dạ các dự án nhận đủ 60 tuổi")
    assert captured["allowed_tools"] == ("list_active_projects", "search_knowledge")
    assert captured["required_tool"] == "list_active_projects"
    assert "ĐỦ ĐIỀU KIỆN THEO TUỔI" in captured["prompt"]
    assert "KHÔNG hỏi lại" in captured["prompt"]


@pytest.mark.asyncio
async def test_age_statement_without_question_keeps_the_normal_route(monkeypatch):
    """A candidate stating their age is a profile fact, not an eligibility gate.

    "em 25 tuổi, ở Hải Phòng ạ" carries no question marker: no forced catalog,
    no eligibility hint — the normal route (and its own hint) applies.
    """
    from app.graph.runner import _agent_turn

    captured: dict[str] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            captured["prompt"] = user_text
            return "Dạ em đã ghi nhận ạ."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    await _agent_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="em 25 tuổi, ở Hải Phòng ạ",
        ),
        deps,
        "em 25 tuổi, ở Hải Phòng ạ",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        project_context=SimpleNamespace(
            state="EXPLORE", knowledge_mode=None, project_slug=None, project_name=None
        ),
        decisions=TurnDecisions(intent="profile_update", intent_confidence=0.9),
    )

    assert captured.get("required_tool") != "list_active_projects"
    assert "ĐỦ ĐIỀU KIỆN THEO TUỔI" not in captured["prompt"]


@pytest.mark.parametrize("mode", ["RAG", "DIRECT_CONTEXT"])
@pytest.mark.parametrize("decisions", [
    TurnDecisions(intent="general", intent_confidence=0.8, recent_vacancy=True),
    TurnDecisions(intent="recommend", intent_confidence=0.95, vacancy_listing=True),
])
async def test_focused_context_preserves_required_catalog_authority(monkeypatch, mode, decisions):
    """A focused KB cannot replace the catalog authority for a catalog turn."""
    captured = {}

    class Agent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "Danh mục dự án đang tuyển đã xác minh."

    monkeypatch.setattr("app.graph.context.build_system_prompt", AsyncMock(
        return_value=("recruitment prompt", False),
    ))
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = Agent()
    deps.lead = SimpleNamespace(
        context=AsyncMock(return_value=("", "")), instruction=lambda _question: "",
    )
    context = ProjectTurnContext(
        state="FOCUSED", project_slug="focused-project", project_name="Focused project",
        knowledge_mode=mode,
        direct_context=(
            DirectContext("kb", "", "Only the focused project's details.")
            if mode == "DIRECT_CONTEXT" else None
        ),
    )
    await lanes._agent_turn(
        _state(), deps, "còn dự án nào nữa?", provider="zalo_bot", chat_id="z1",
        recent_messages=[], project_context=context, decisions=decisions, timings={},
    )
    assert captured["required_tool"] == "list_active_projects"
    assert captured["allowed_tools"] == ("list_active_projects",)
    assert captured.get("resolved_tool_registry") != frozenset()
    assert "forced_project_slug" not in captured


@pytest.mark.parametrize("mode", ["RAG", "DIRECT_CONTEXT"])
async def test_focused_salary_target_remains_scoped_to_its_project(monkeypatch, mode):
    """A target salary in a focused conversation does not widen project scope."""
    captured = {}

    class Agent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "Thu nhập của dự án đã chọn được đối chiếu với kiến thức dự án."

    monkeypatch.setattr("app.graph.context.build_system_prompt", AsyncMock(
        return_value=("recruitment prompt", False),
    ))
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = Agent()
    deps.lead = SimpleNamespace(
        context=AsyncMock(return_value=("", "")), instruction=lambda _question: "",
    )
    context = ProjectTurnContext(
        state="FOCUSED", project_slug="focused-project", project_name="Focused project",
        knowledge_mode=mode,
        direct_context=(DirectContext("kb", "", "Thu nhập đã xác minh.") if mode == "DIRECT_CONTEXT" else None),
    )
    await lanes._agent_turn(
        _state(), deps, "lương 20 triệu", provider="zalo_bot", chat_id="z1",
        recent_messages=[], project_context=context,
        decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.9), timings={},
    )
    if mode == "RAG":
        assert captured["required_tool"] == "search_knowledge"
        assert captured["forced_project_slug"] == "focused-project"
    else:
        assert captured.get("required_tool") is None
        assert captured["resolved_tool_registry"] == frozenset()


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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

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
    assert captured["allowed_tools"] == ("list_active_projects",)
    assert captured["required_tool"] == "list_active_projects"
    assert captured["required_tool_args"] is None


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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

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
    assert captured["allowed_tools"] == ("list_active_projects",)
    assert captured["required_tool"] == "list_active_projects"
    assert captured["required_tool_args"] is None


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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])

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

    assert captured["allowed_tools"] == (
        "get_product_features",
        "search_knowledge",
        "load_project_knowledge",
    )
    assert "lG tràng duệ" in str(captured["lookup_query"])
    assert query in str(captured["lookup_query"])
    assert "required_tool" not in captured


@pytest.mark.asyncio
async def test_support_oa_turn_injects_the_guide_and_only_the_reset_tools(monkeypatch):
    """On the TingTing OA the reset flow is the whole toolset.

    Regression: the API guide used to be gated behind a FOCUSED project, so an
    employee asking to reset a password never saw the endpoints. Now the support
    OA always sees the guide — and nothing else: no project catalog, no
    recruiting knowledge, so a stray route cannot answer a candidate question
    from the employee channel.
    """
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "safe reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988")
    )

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="quên mật khẩu app"),
        deps,
        "quên mật khẩu app",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="employee_support", intent_confidence=0.92, login_problem=True),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
    )

    system = str(captured["system"])
    assert "=== API TINGTING" in system
    assert "/api/v1/integration/password-reset/otp" in system
    assert set(captured["allowed_tools"]) == {
        "verify_tingting_identity",
        "send_tingting_otp",
        "confirm_tingting_otp",
        "reset_tingting_password",
        "send_self_checkin_otp",
        "confirm_self_checkin_otp",
        "update_self_checkin",
        "check_self_checkin_status",
    }


@pytest.mark.asyncio
async def test_agent_turn_omits_the_tingting_guide_when_unconfigured(monkeypatch):
    """No key configured → no endpoint instructions, so no unfulfillable promise."""
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "safe reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=False),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988")
    )

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="quên mật khẩu app"),
        deps,
        "quên mật khẩu app",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="employee_support", intent_confidence=0.92, login_problem=True),
        tingting_reset_allowed=True,
    )

    system = str(captured["system"])
    assert "=== API TINGTING" not in system
    assert "/api/v1/integration/password-reset/otp" not in system


@pytest.mark.asyncio
async def test_off_channel_support_turn_gets_the_pointer_to_the_support_oa(monkeypatch):
    """Off the support OA the answer is a fixed string, not a model output.

    The operator approved these exact words: they name the TingTing OA and link
    to it, and nothing else — no invented hotline, no paraphrase that could drop
    the link.
    """
    from app.graph.runner import TINGTING_RESET_REDIRECT_REPLY, _agent_turn

    captured: dict[str, object] = {}
    direct_calls: list[dict] = []

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "direct reply"

        async def direct(self, user_text, **kwargs):
            direct_calls.append(kwargs)
            return "direct reply"

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988")
    )

    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="quên mật khẩu app"),
        deps,
        "quên mật khẩu app",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="employee_support", intent_confidence=0.92, login_problem=True),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=False,
    )

    assert reply == TINGTING_RESET_REDIRECT_REPLY
    assert "Zalo OA Ting Ting Software Solution" in reply
    assert "https://zalo.me/3383849659955472174" in reply
    assert captured == {}  # no generation at all
    assert direct_calls == []


@pytest.mark.asyncio
async def test_a_recruitment_question_on_the_support_oa_points_at_the_hotline():
    """A confident non-support question on the support OA gets the hotline reply.

    Operator rule (2026-09-29): nobody works the TingTing OA as a human, so the
    hotline reply IS the handoff — no model call, no human queue write.
    """
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}
    escalations: list[dict] = []

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "should not run"

    class _Conversations:
        async def get(self, _conversation_id):
            return SimpleNamespace(id=CONV_ID, version=7)

        async def escalate_extracted_intent(
            self, conv, *, reason, confidence, expected_version, preserve_turn_ownership=False
        ):
            escalations.append(
                {
                    "conversation": conv,
                    "reason": reason,
                    "confidence": confidence,
                    "expected_version": expected_version,
                    "preserve_turn_ownership": preserve_turn_ownership,
                }
            )
            return True

    deps = _deps(_FakeZalo(), conversation=_Conversations())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(tingting_hotline=AsyncMock(return_value="+84 914 827 988"))

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=7, user_text="dự án nào lương cao"),
        deps,
        "dự án nào lương cao",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.9),
        tingting_reset_allowed=True,
    )

    assert reply == TINGTING_HOTLINE_REPLY
    assert "914827988" in reply.replace(" ", "")
    assert captured == {}  # the model never answers on this channel
    assert escalations == []  # nothing is queued — the hotline is the handoff


def test_the_recruitment_handoff_points_at_the_fixed_facts_hotline():
    """Operator rule (2026-09-29): the off-scope refusal points candidates at the
    VFIC hotline. The number is no longer a code-authored reply — it lives in the
    system prompt's SỰ THẬT CỐ ĐỊNH block, and the router instruction tells the
    model to offer exactly that number. The TingTing support OA has its own
    number (same day's OA ruling), so the two must never drift together.
    """
    from app.graph import context
    from app.graph.router import TurnRoute, routing_instruction

    instruction = routing_instruction(
        TurnRoute("out_of_scope", "safe_redirect", reason="off_domain_terms")
    )
    assert "SỰ THẬT CỐ ĐỊNH" in instruction
    assert "1800 7228" in context._RUNTIME_RETRIEVAL_RULES
    assert "914827988" in TINGTING_HOTLINE_REPLY.replace(" ", "")


@pytest.mark.asyncio
async def test_a_confident_off_domain_turn_ships_the_fixed_hotline_reply():
    """A confident off-scope turn is answered by the fixed hotline reply.

    Supersedes the 2026-09-29 model-authored refusal: the tax-question case
    (operator rule 2026-10-03) showed the model answering content it should
    hand off, so a confident read now returns the approved verbatim line and
    the model never runs. The hotline IS the handoff — no phone-number
    interlude, no human queue write. Below the floor a reading means "cannot
    tell" and the model still authors (next test).
    """
    from app.graph.runner import _agent_turn
    from app.prompts.vfic_persona import vfic_hotline_reply

    captured: dict[str, object] = {}
    escalations: list[dict] = []

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            captured["system"] = kwargs.get("system", "")
            return "model prose must never ship here"

    class _Conversations:
        async def get(self, _conversation_id):
            return SimpleNamespace(id=CONV_ID, version=7)

        async def escalate_extracted_intent(self, conv, **kwargs):
            escalations.append(kwargs)
            return True

    deps = _deps(_FakeZalo(), conversation=_Conversations())
    deps.agent = _FakeAgent()

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=7, user_text="tính thuế TNCN cho em"),
        deps,
        "tính thuế TNCN cho em",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="out_of_scope", intent_confidence=0.9),
    )

    assert reply == vfic_hotline_reply()
    assert "1800 7228" in reply
    assert captured == {}  # the model never runs on a confident handoff
    assert escalations == []  # the hotline is the handoff — nobody is queued


@pytest.mark.asyncio
async def test_a_not_job_seeker_never_reaches_the_model():
    """Operator rule (2026-10-03): a non-seeker's turn ships the hotline reply.

    Pins the first prod failure: an existing worker whose probation contract
    expired ("Hợp đồng thử việc cũng hết rồi") read as ``recommend`` and got
    project pitches. The route reason gates before any model or tool work, so
    the pitch cannot happen, and the reason is stamped for the dashboard.
    """
    from app.graph.runner import _agent_turn
    from app.prompts.vfic_persona import vfic_hotline_reply

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            return "Dạ anh đang muốn tìm công việc mới phải không ạ?"

    class _Conversations:
        async def get(self, _conversation_id):
            return SimpleNamespace(id=CONV_ID, version=7)

        async def escalate_extracted_intent(self, conv, **kwargs):  # noqa: ARG001
            return True

    deps = _deps(_FakeZalo(), conversation=_Conversations())
    deps.agent = _FakeAgent()
    timings: dict = {"lane": "agent"}

    reply = await _agent_turn(
        BotRunState(
            conversation_id=CONV_ID, version_at_start=7, user_text="Hợp đồng thử việc cũng hết rồi"
        ),
        deps,
        "Hợp đồng thử việc cũng hết rồi",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings=timings,
        decisions=TurnDecisions(
            intent="recommend", intent_confidence=0.91, job_seeking="not_seeking"
        ),
    )

    assert reply == vfic_hotline_reply()
    assert captured == {}  # the model never runs — no pitch, no nonsense
    assert timings["route_reason"] == "not_job_seeking"
    assert "tool_call_counts" not in timings  # no tool round happened


@pytest.mark.asyncio
async def test_a_barely_confident_off_domain_reading_is_still_answered_by_the_model():
    """Below the floor means "cannot tell" — that must not cost a lead its bot.

    Handing a working recruiting conversation to a human on a low-confidence
    reading is the expensive error, so the floor guards the start of the flow.
    """
    from app.graph.router import TurnRoute
    from app.graph.runner import _agent_turn

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            return "Dạ bên mình có tuyển công nhân ở Hải Phòng ạ."

    class _FakeLead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    def _uncertain_route(_text, _decisions):
        return TurnRoute("out_of_scope", "safe_redirect", reason="off_domain_terms", confidence=0.3)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"])
    monkeypatch.setattr(lanes, "route_from_decisions", _uncertain_route)

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

    try:
        reply = await _agent_turn(
            BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="cho em hỏi lương"),
            deps,
            "cho em hỏi lương",
            provider="zalo_bot",
            chat_id="z1",
            recent_messages=[],
            timings={"lane": "agent"},
            decisions=TurnDecisions(intent="out_of_scope", intent_confidence=0.3),
        )
    finally:
        monkeypatch.undo()

    assert "tuyển công nhân" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decisions",
    [
        # "Tôi cần hỗ trợ" — the employee wants help and has not said with what.
        pytest.param(TurnDecisions(intent="general", intent_confidence=0.9), id="unspecified"),
        # Jev read it as something else, but with nothing behind the reading.
        pytest.param(TurnDecisions(intent="faq_detail", intent_confidence=0.2), id="low-confidence"),
        # "Chào bạn" — a conversation opener, not a request for a person.
        pytest.param(
            TurnDecisions(intent="small_talk", intent_confidence=0.9, pleasantry=True),
            id="greeting",
        ),
    ],
)
async def test_an_unclear_message_on_the_support_oa_makes_the_bot_ask_first(
    monkeypatch, decisions
):
    """An employee who has not named a problem gets a question, not a queue slot.

    The agent runs on the reset toolset and asks which problem they have; nothing
    is escalated, so the answer to that question starts the reset flow on the
    next turn instead of leaving them parked in the human queue.
    """
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}
    escalations: list[dict] = []

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "Dạ anh/chị đang gặp vấn đề gì ạ?"

    class _Conversations:
        async def get(self, _conversation_id):
            return SimpleNamespace(id=CONV_ID, version=7)

        async def escalate_extracted_intent(self, conv, **_kwargs):
            escalations.append(conv)
            return True

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=_Conversations())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    timings: dict = {"lane": "agent"}
    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=7, user_text="Tôi cần hỗ trợ"),
        deps,
        "Tôi cần hỗ trợ",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings=timings,
        decisions=decisions,
        tingting_reset_allowed=True,
    )

    assert reply == "Dạ anh/chị đang gặp vấn đề gì ạ?"
    assert set(captured["allowed_tools"]) == {
        "verify_tingting_identity",
        "send_tingting_otp",
        "confirm_tingting_otp",
        "reset_tingting_password",
        "send_self_checkin_otp",
        "confirm_self_checkin_otp",
        "update_self_checkin",
        "check_self_checkin_status",
    }
    # The turn is served as the reset flow (so the next message can continue it)…
    assert timings["intent"] == "employee_support"
    # …and nobody was called in.
    assert escalations == []


@pytest.mark.asyncio
async def test_support_oa_turn_uses_the_tingting_prompt_not_the_recruitment_one(monkeypatch):
    """The OA's system prompt is the code persona — the recruitment prompt is unreachable.

    Regression for the production transcript: the OA inherited ``persona.md``
    ("nhân viên hỗ trợ tuyển dụng VFIC", mission "LẤY SỐ ĐIỆN THOẠI") plus the
    active-project index, so a request to look up someone introduced the bot as a
    VFIC recruiting assistant. ``build_system_prompt`` must not even be consulted
    on this channel, and the non-OA branch must still reach it unchanged.
    """
    from app.graph.runner import _agent_turn
    from app.graph.tingting_guide import (
        TINGTING_API_BLOCK_HEADER,
        tingting_support_persona,
    )

    TINGTING_SUPPORT_PERSONA = tingting_support_persona("+84 914 827 988")

    captured: dict[str, object] = {}
    prompt_calls: list[str] = []

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "safe reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        prompt_calls.append("called")
        return "RECRUITMENT-PERSONA-MARKER", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    async def _turn(*, allowed: bool) -> str:
        captured.clear()
        await _agent_turn(
            BotRunState(
                conversation_id=CONV_ID, version_at_start=1, user_text="tra cứu Nguyễn Văn A"
            ),
            deps,
            "tra cứu Nguyễn Văn A",
            provider="zalo_oa",
            chat_id="oa:user-1",
            recent_messages=[],
            timings={"lane": "agent"},
            decisions=TurnDecisions(intent="general", intent_confidence=0.2),
            tingting_reset_allowed=allowed,
        )
        return str(captured["system"])

    system = await _turn(allowed=True)
    assert system.startswith(TINGTING_SUPPORT_PERSONA)
    assert TINGTING_API_BLOCK_HEADER in system
    assert "RECRUITMENT-PERSONA-MARKER" not in system
    assert prompt_calls == []  # the recruitment prompt was never built for the OA

    off_channel = await _turn(allowed=False)
    assert "RECRUITMENT-PERSONA-MARKER" in off_channel
    assert prompt_calls == ["called"]


@pytest.mark.asyncio
async def test_support_oa_keeps_the_support_prompt_when_the_reset_link_pin_is_unset(
    monkeypatch,
):
    """The prompt gate is identity-only: no admin pin → still no recruitment preamble.

    ``tingting_reset_allowed`` (the pin-gated reset-flow flag) is False here, so
    before the identity branch this turn fell through to ``build_system_prompt``
    and served the project directory and recruiting rules on the support OA.
    """
    from app.graph.runner import _agent_turn
    from app.graph.tingting_guide import tingting_support_persona

    TINGTING_SUPPORT_PERSONA = tingting_support_persona("+84 914 827 988")

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "safe reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "RECRUITMENT-PERSONA-MARKER", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=False),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="hello"),
        deps,
        "hello",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="general", intent_confidence=0.2),
        tingting_reset_allowed=False,
        tingting_support_account=True,
    )

    system = str(captured["system"])
    assert system.startswith(TINGTING_SUPPORT_PERSONA)
    assert "RECRUITMENT-PERSONA-MARKER" not in system


def test_tingting_support_account_identity_is_pin_free():
    """The identity check matches the OA account and nothing else.

    A messenger account that happens to carry the key does not count, the
    recruitment OA never does, and conversations without an identity row are
    recruitment-scoped by default.
    """
    from app.graph.lanes import _tingting_account_conversation

    def _conv(provider, account_key):
        return SimpleNamespace(
            channel_identity=SimpleNamespace(provider=provider, account_key=account_key)
        )

    assert _tingting_account_conversation(_conv("zalo_oa", "tingting")) is True
    assert _tingting_account_conversation(_conv("zalo_oa", "default:zalo_oa")) is False
    assert _tingting_account_conversation(_conv("facebook_messenger", "tingting")) is False
    assert _tingting_account_conversation(_conv("zalo_bot", "tingting")) is False
    assert _tingting_account_conversation(SimpleNamespace(channel_identity=None)) is False
    assert _tingting_account_conversation(object()) is False


@pytest.mark.asyncio
async def test_support_oa_never_takes_the_curated_recruitment_lanes(monkeypatch):
    """Pin-unset TingTing turns never carry recruitment clarification/direct context.

    The agent now authors every reply, so both curated lanes became agent inputs
    (a mandatory instruction; a folded direct-context block). The identity flag
    gates them the same way it gates the prompt branch: the support OA gets an
    empty mandatory instruction, and a recruitment-OA control proves the flag is
    what withheld it.
    """
    from app.graph.lanes import _resolve_lane

    tingting_conv = SimpleNamespace(
        channel_identity=SimpleNamespace(provider="zalo_oa", account_key="tingting")
    )
    recruit_conv = SimpleNamespace(
        channel_identity=SimpleNamespace(provider="zalo_oa", account_key="default:zalo_oa")
    )
    turn_route = SimpleNamespace(intent="general", reason="faq", confidence=0.9)
    clarification_ctx = SimpleNamespace(
        clarification="Anh muốn tìm hiểu lương dự án nào ạ?",
        direct_context=None,
        state="EXPLORE",
        knowledge_mode="DIRECT_CONTEXT",
    )

    class _LaneAgent:
        def __init__(self) -> None:
            self.kwargs: dict | None = None

        async def __call__(self, state, deps, user_text, **kwargs):  # noqa: ARG002
            self.kwargs = kwargs
            return "ok"

    async def _run(conv, project_context):
        agent = _LaneAgent()
        resolution = await _resolve_lane(
            state=_state(),
            deps=_deps(_FakeZalo(), conversation=object()),
            conv=conv,
            svc=object(),
            decisions=TurnDecisions(intent="general", intent_confidence=0.9),
            turn_route=turn_route,
            project_context=project_context,
            recent_messages=[],
            manifest_policy=None,
            provider="zalo_oa",
            recipient_id="oa:u1",
            timings={},
            started=None,
            lock_owner=None,
            status_task=None,
            t0=0.0,
            tingting_reset_allowed=False,
            agent_turn=agent,
        )
        return resolution, agent

    # A stale clarification on the support OA must not read like recruitment.
    resolution, agent = await _run(tingting_conv, clarification_ctx)
    assert resolution.lane == "agent"
    assert agent.kwargs["tingting_support_account"] is True
    assert agent.kwargs["mandatory_instruction"] == ""

    # Control: the same context on the recruitment OA still asks the question.
    control, agent = await _run(recruit_conv, clarification_ctx)
    assert control.lane == "agent"
    assert "PHẢI hỏi lại ứng viên muốn hỏi dự án nào" in agent.kwargs["mandatory_instruction"]

    # A direct-context hit on the support OA must not leak project KB text; the
    # direct-context block is folded inside ``_agent_turn``, gated the same way.
    direct_ctx = SimpleNamespace(
        clarification=None,
        direct_context=SimpleNamespace(knowledge_base_id=7),
        state="EXPLORE",
        knowledge_mode="DIRECT_CONTEXT",
    )
    resolution, agent = await _run(tingting_conv, direct_ctx)
    assert resolution.lane == "agent"
    assert agent.kwargs["tingting_support_account"] is True
    assert agent.kwargs["mandatory_instruction"] == ""

    # Control: the recruitment OA keeps the agent lane with no withheld flag.
    control, agent = await _run(recruit_conv, direct_ctx)
    assert control.lane == "agent"
    assert agent.kwargs["tingting_support_account"] is False
    assert agent.kwargs["mandatory_instruction"] == ""


@pytest.mark.asyncio
async def test_support_oa_hotline_reply_queues_nothing(monkeypatch):
    """The dictated hotline reply passes through with no queue write.

    The model can emit the fixed reply verbatim (an unclear reading of a
    non-reset request, or the exhaustion tail the tool dictates). Operator rule
    (2026-09-29): no reply wording triggers a queue write anymore — the hotline
    reply itself is the handoff, so it must flow through untouched.
    """
    from app.graph.runner import _agent_turn

    escalations: list[dict] = []

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            return TINGTING_HOTLINE_REPLY

    class _Conversations:
        async def get(self, _conversation_id):
            return SimpleNamespace(id=CONV_ID, version=7)

        async def escalate_extracted_intent(self, conv, **kwargs):
            escalations.append({"conversation": conv, **kwargs})
            return True

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=_Conversations())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=7, user_text="Tôi cần hỗ trợ"),
        deps,
        "Tôi cần hỗ trợ",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="general", intent_confidence=0.2),
        tingting_reset_allowed=True,
    )

    assert reply == TINGTING_HOTLINE_REPLY
    assert escalations == []  # the hotline IS the handoff — nobody is queued


@pytest.mark.asyncio
async def test_focused_support_turn_drops_the_project_knowledge_tool(monkeypatch):
    """A FOCUSED project turn on the support OA cannot re-add project knowledge.

    The focused branch binds one Project-owned knowledge authority; on the
    employee OA that must not happen — the reset tools are the whole surface.
    """
    from app.graph.runner import _agent_turn

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return "safe reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988")
    )

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="em quên mật khẩu"),
        deps,
        "em quên mật khẩu",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="employee_support", intent_confidence=0.95, login_problem=True),
        project_context=ProjectTurnContext(
            state="FOCUSED",
            project_id="p1",
            project_slug="lg-display",
            project_name="LG Display",
            knowledge_mode="RAG",
        ),
        tingting_reset_allowed=True,
    )

    assert set(captured["allowed_tools"]) == {
        "verify_tingting_identity",
        "send_tingting_otp",
        "confirm_tingting_otp",
        "reset_tingting_password",
        "send_self_checkin_otp",
        "confirm_self_checkin_otp",
        "update_self_checkin",
        "check_self_checkin_status",
    }
    assert "search_knowledge" not in captured["allowed_tools"]

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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kw: kw["current_user_text"])

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
async def test_new_candidate_lead_miss_is_not_queried_again_during_the_turn(monkeypatch):
    from app.recruitment.application.lead_lookup import UNRESOLVED_LEAD
    from app.recruitment.infrastructure import service_adapters

    resolve = AsyncMock(return_value=None)
    captured: list[object] = []

    async def agent_turn(*_args, lead_row=UNRESOLVED_LEAD, **_kwargs):
        captured.append(lead_row)
        return "Em có thể tư vấn công việc cho chị."

    monkeypatch.setattr(service_adapters, "_resolve_lead", resolve)
    monkeypatch.setattr(runner, "_agent_turn", agent_turn)
    svc, _ = _stub_svc(conv=_FakeConv())
    deps = _deps(_FakeZalo(), conversation=svc)
    deps.lead_gender = service_adapters.ServiceLeadGenderAdapter(object())
    deps.turn_decisions = _decisions_port(
        TurnDecisions(gender="female", gender_confidence=0.9)
    )

    result = await run_turn(_state(), deps)

    assert result["outcome"] == "sent"
    resolve.assert_awaited_once()
    assert captured == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_lead", [False, True])
@pytest.mark.parametrize("refresh_failure", [False, True])
async def test_profile_name_capture_refreshes_prefetch_before_prompt_context(
    monkeypatch, existing_lead, refresh_failure
):
    from app.recruitment.application.lead_lookup import UNRESOLVED_LEAD
    from app.recruitment.infrastructure import service_adapters

    contact_id = "contact-profile"
    name = "Nguyễn Văn Hùng"
    saved = {"id": 9, "contact_id": contact_id, "name": None} if existing_lead else None
    reads: list[dict | None] = []
    profiles: list[str] = []
    writes: list[dict] = []
    refresh_failed = False

    class Repository:
        def __init__(self, _db):
            pass

        async def by_contact_id(self, _contact_id):
            nonlocal refresh_failed
            row = dict(saved) if saved is not None else None
            reads.append(row)
            if writes and refresh_failure and not refresh_failed:
                refresh_failed = True
                raise RuntimeError("refresh unavailable")
            return row

        async def upsert_by_contact(self, _contact_id, patch):
            nonlocal saved
            writes.append(patch)
            saved = {"id": 9, "contact_id": contact_id, "name": patch["name"]}
            return saved["id"]

    async def agent_turn(_state, deps, user_text, *, lead_row=UNRESOLVED_LEAD, **kwargs):
        profile, _ = await deps.lead.context(
            kwargs["chat_id"], user_text, kwargs["recent_messages"],
            contact_id=kwargs["contact_id"], lead=lead_row,
        )
        profiles.append(profile)
        return "Em có thể hỗ trợ tìm việc cho anh."

    monkeypatch.setattr("app.services.lead.repository.LeadRepository", Repository)
    monkeypatch.setattr(runner, "_agent_turn", agent_turn)
    conv = _FakeConv(
        zalo_chat_id=None, zalo_channel="facebook_messenger", contact_id=contact_id,
        channel_identity=SimpleNamespace(provider="facebook_messenger", external_id="candidate"),
    )
    conv.contact = SimpleNamespace(display_name=name)
    svc, _ = _stub_svc(conv=conv, durable=True)
    deps = _deps(_FakeZalo(), conversation=svc)
    db = SimpleNamespace(commit=AsyncMock())
    deps.lead_gender = service_adapters.ServiceLeadGenderAdapter(db)
    deps.lead = service_adapters.ServiceLeadContextAdapter(db)
    deps.turn_decisions = _decisions_port(TurnDecisions(profile_name_is_name=True))

    result = await run_turn(_state(), deps)

    assert result["outcome"] == "sent"
    assert len(writes) == 1
    assert name in profiles[0]
    assert len(reads) == (3 if refresh_failure else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("lead_row", [{"id": 5, "zalo_id": "z1", "gender": "female"}, None])
async def test_agent_turn_passes_the_resolved_lead_row_to_context(monkeypatch, lead_row):
    from app.graph.runner import _agent_turn
    from app.recruitment.application.lead_lookup import UNRESOLVED_LEAD

    captured: dict[str, object] = {}

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _FakeLead:
        async def context(
            self, chat_id, current_user_text, recent_messages, contact_id=None,
            lead=UNRESOLVED_LEAD,
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
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kw: kw["current_user_text"])

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _FakeLead()

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


def test_progressive_boundary_never_cuts_inside_a_number():
    """A dot between digits is a Vietnamese thousands separator, not a period.

    «…hỗ trợ 30.000 VND/ngày…» must stay whole: the bubble boundary is the next
    real sentence end, so one amount can never straddle two bubbles.
    """
    raw = (
        "Dạ về phúc lợi tại kho, anh/chị được hưởng các quyền lợi sau: "
        "Cơm ca trưa miễn phí, hoặc hỗ trợ 30.000 VND/ngày nếu không ăn cơm ca. "
        "Xe đưa đón miễn phí tại các điểm trung tâm nội thành Hải Phòng."
    )
    offset = runner._next_sendable_offset(raw, min_offset=1)
    assert raw[offset - 1] == "."
    assert "30.000 VND/ngày nếu không ăn cơm ca." in raw[:offset]
    assert not raw[:offset].rstrip().endswith("30.")


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
    shipped = svc.dispatched[0]["text"]
    assert shipped == raw
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
    shipped = svc.dispatched[0]["text"]
    assert shipped == raw
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


def test_agent_rules_quote_the_redirect_reply_when_reset_tools_are_absent():
    """The exact-reply guard only fires on a classified employee_support intent.

    When routing misclassifies the message, the model still must redirect the
    employee with the operator's exact words — OA name and clickable link
    included — so the static agent rules quote the reply verbatim and forbid
    paraphrase.
    """
    from app.graph.context import _RUNTIME_RETRIEVAL_RULES
    from app.graph.tingting_guide import TINGTING_RESET_REDIRECT_REPLY

    assert TINGTING_RESET_REDIRECT_REPLY in _RUNTIME_RETRIEVAL_RULES



# ─── progressive bubbles on terminal paths ───────────────────────────────────
#
# Once the early bubble is dispatched, that message row is SENDING with the real
# text stamped into it. Only the success path used to terminalize it, so every
# failure path recorded the SAME pending_message_id with reply="" — which matched
# the row, blanked its body, and (through the delivery-rank tie) let the empty
# status win. The candidate kept a cut-off answer under an empty suppressed
# message, and the timeout variant made the sweep answer them twice.


def _aborting_after_bubble(svc, parts):
    """A streaming agent that ships its bubble, then crashes.

    This is the shape of a provider dying after progressive send: the early
    sender dispatches the bubble, and the lane then raises so the runner's
    stand-down exit records the turn.
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
        **kwargs,
    ):  # noqa: ARG001
        for part in parts:
            await on_delta(part)
        # Give the concurrent early sender every chance to dispatch the bubble
        # before the crash (deterministic: no wall-clock wait).
        for _ in range(40):
            await asyncio.sleep(0)
        assert svc.early_dispatched.is_set(), "the early bubble never went out"
        raise RuntimeError("provider died after the early bubble")

    return _fake


@pytest.mark.asyncio
async def test_dispatched_early_bubble_is_recorded_on_the_turn_state(monkeypatch):
    """The bubble is on the turn state the moment it is dispatched.

    Everything downstream — the silent record, the worker's LLMThrottled
    handler, the crash guard — reads the turn state; nothing else can see the
    bubble.
    """
    conv = _FakeConv()
    svc, _recorded = _stub_svc(conv=conv, durable=True)
    _stub_streaming_agent(monkeypatch, _ANSWER_SENTENCES, svc=svc, pause_after=2)
    offset = runner._next_sendable_offset(_ANSWER)
    state = _state()

    await run_turn(state, _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    bubble = runner.delivered_bubble(state)
    assert bubble is not None
    assert bubble.text == _ANSWER[:offset]
    assert bubble.message_id == 777
    assert bubble.outbox_id == 777
    assert bubble.ok is True
    assert runner.delivered_bubble_payload(bubble)["text"] == _ANSWER[:offset]


@pytest.mark.asyncio
async def test_turn_without_progressive_send_records_no_bubble(monkeypatch):
    """The channel stays empty when nothing was delivered early.

    Flag off means no stream and no early sender at all, so there is nothing to
    record — the terminal paths must keep reading "nothing was sent".
    """
    conv = _FakeConv()
    svc, _recorded = _stub_svc(conv=conv)
    _stub_streaming_agent(monkeypatch, _ANSWER_SENTENCES, svc=svc)
    state = _state()

    await run_turn(state, _deps(_FakeZalo(), conversation=svc, progressive_send=False))

    assert runner.delivered_bubble(state) is None
    assert runner.delivered_bubble_payload(None) is None


@pytest.mark.asyncio
async def test_agent_crash_after_the_early_bubble_never_records_an_empty_reply(monkeypatch):
    """A lane that dies AFTER the bubble shipped records the bubble, not "".

    The bubble's outbox row is finalized FIRST, so ``record_bot_outcome`` matches
    an already-terminal row: the body it stamps is the text the candidate is
    reading, and the delivery-rank tie cannot demote a delivered row to a
    suppressed one.
    """
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    # Four sentences so the raw stream clears the 250-char bubble floor.
    parts = _ANSWER_SENTENCES[:4]
    offset = runner._next_sendable_offset("".join(parts))
    monkeypatch.setattr(runner, "_agent_turn", _aborting_after_bubble(svc, parts))

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    # The bubble is terminalized on its own outbox row, with no recovery BotRun.
    assert svc.finalized[0]["message_id"] == 777
    assert svc.finalized[0]["outbox_id"] == 777
    assert svc.finalized[0]["delivered"] is True
    assert svc.finalized[0]["telemetry"] is None
    # ...and the turn's own audit row carries the delivered text, sent=True.
    assert len(recorded) == 1
    assert recorded[0]["reply"] == "".join(parts)[:offset]
    assert recorded[0]["reply"] != ""
    assert recorded[0]["sent"] is True
    assert recorded[0]["pending_message_id"] == 777
    assert recorded[0]["stage_timings"]["progressive_bubble_finalized"] is True
    # Nothing was sent after the bubble: no second dispatch, no second placeholder.
    assert len(svc.dispatched) == 1
    assert res["reply"] == "".join(parts)[:offset]


@pytest.mark.asyncio
async def test_progressive_stream_mismatch_is_recorded_as_alarmable(monkeypatch):
    """A mid-stream provider replacement is a dashboard+alarm signal, not a note.

    ``stream.raw`` is the accumulation of every delta, so it IS the transcript the
    candidate's messages are built from; when it no longer equals the returned
    answer the turn is structurally partial, and the frequency is the health
    signal for mid-stream replacement.
    """
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    replacement = "Một câu trả lời hoàn toàn khác do nhà cung cấp dự phòng sinh ra."
    _stub_streaming_agent(monkeypatch, _ANSWER_SENTENCES, svc=svc, full=replacement)

    res = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert res["outcome"] == "sent"
    stage = recorded[0]["stage_timings"]
    assert stage["progressive_stream_mismatch"] is True
    assert stage["progressive_stream_mismatch_chars"] == abs(
        len(_ANSWER) - len(replacement)
    )
    assert svc.dispatched[-1]["text"] == replacement
    assert recorded[0]["reply"] == replacement


@pytest.mark.asyncio
async def test_progressive_suppressed_final_answer_does_not_send_rejected_raw_tail(monkeypatch):
    """A delivered prefix stays durable, but a rejected final tail stays private."""
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    _stub_streaming_agent(monkeypatch, _ANSWER_SENTENCES, svc=svc, full="", pause_after=2)

    result = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert len(svc.dispatched) == 1
    assert recorded[0]["sent"] is True
    assert recorded[0]["reply"] == svc.dispatched[0]["text"]
    assert result["reply"] == svc.dispatched[0]["text"]
    assert len(svc.claims) == 1


@pytest.mark.asyncio
async def test_catalog_list_waits_for_final_completion_before_any_candidate_delivery(monkeypatch):
    """Project discovery cannot publish its first two rows before all rows finish."""
    from app.graph.tools.catalog import _project_tool_result

    names = ("LG Display", "Rorze", "Amtran", "Kyocera", "Pegatron")
    evidence = _project_tool_result("matched", [
        {"id": str(uuid.uuid4()), "project": name} for name in names
    ], "Present verified projects.", total=5)
    parts = [
        "LG Display, Rorze: " + "Thông tin dự án đã được xác minh. " * 10,
        "Amtran, Kyocera, Pegatron: công việc sản xuất tại Hải Phòng.",
    ]
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    _stub_streaming_agent(monkeypatch, parts, svc=svc, evidence=[evidence], full="")

    result = await run_turn(_state(), _deps(_FakeZalo(), conversation=svc, progressive_send=True))

    assert result["outcome"] == "suppressed"
    assert svc.dispatched == []
    assert svc.agent_returned_after_dispatches == [0]
    assert recorded[0]["stage_timings"]["progressive_first_bubble_skipped"] == "catalog_completeness"


@pytest.mark.parametrize("decisions", [
    TurnDecisions(intent="recommend", intent_confidence=0.95, vacancy_listing=True),
    TurnDecisions(intent="general", intent_confidence=0.7, recent_vacancy=True),
])
@pytest.mark.asyncio
async def test_catalog_route_cannot_send_preface_before_the_authority_tool(monkeypatch, decisions):
    conv = _FakeConv()
    svc, recorded = _stub_svc(conv=conv, durable=True)
    # A provider may stream prose before it announces its tool request. This
    # is not yet catalog evidence and must never become a candidate message.
    _stub_streaming_agent(monkeypatch, _ANSWER_SENTENCES, svc=svc, full="")
    deps = _deps(_FakeZalo(), conversation=svc, progressive_send=True)
    deps.turn_decisions = SimpleNamespace(decide_turn=AsyncMock(return_value=decisions))

    result = await run_turn(_state(), deps)

    assert result["outcome"] == "suppressed"
    assert svc.dispatched == []
    assert svc.agent_returned_after_dispatches == [0]
    assert recorded[0]["stage_timings"]["progressive_first_bubble_skipped"] == "catalog_completeness"


@pytest.mark.asyncio
async def test_the_verification_exhaustion_reply_delivers_without_escalating(monkeypatch):
    """The verify tool dictates the exhaustion reply; its hotline tail is the handoff.

    The lane passes the dictated reply through untouched and nothing is queued
    (operator rule 2026-09-29): the hotline IS the handoff, so the employee
    really receives the number instead of a queue entry nobody will work.
    """
    from app.graph import lanes
    from app.graph.runner import _agent_turn
    from app.graph.tingting_guide import tingting_verify_exhausted_reply

    TINGTING_VERIFY_EXHAUSTED_REPLY = tingting_verify_exhausted_reply("+84 914 827 988")

    captured: dict[str, object] = {}
    escalations: list[dict] = []

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):
            captured.update(kwargs)
            return TINGTING_VERIFY_EXHAUSTED_REPLY

    class _Conversations:
        async def get(self, _conversation_id):
            return SimpleNamespace(id=CONV_ID, version=7)

        async def escalate_extracted_intent(
            self, conv, *, reason, confidence, expected_version, preserve_turn_ownership=False
        ):
            escalations.append({"reason": reason, "preserve_turn_ownership": preserve_turn_ownership})
            return True

    deps = _deps(_FakeZalo(), conversation=_Conversations())
    deps.agent = _FakeAgent()
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=7,
            user_text="Nguyễn Việt Dũng cccd 1111999 dt 0357210887",
        ),
        deps,
        "Nguyễn Việt Dũng cccd 1111999 dt 0357210887",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="employee_support", intent_confidence=0.95, login_problem=True),
        tingting_reset_allowed=True,
    )

    assert reply == TINGTING_VERIFY_EXHAUSTED_REPLY
    assert "914827988" in reply.replace(" ", "")
    assert escalations == []  # the hotline IS the handoff — nobody is queued


def test_runtime_rules_carry_the_project_first_sales_directive():
    """Operator rule 2026-10-01: the project is the recruitment unit.

    The agent sells the project even when the Job catalog has no matching
    rows — the DANH MỤC entry (location, summary, highlights) is hiring
    evidence, backed by search_knowledge for details.
    """
    from app.graph.context import _RUNTIME_RETRIEVAL_RULES

    assert "ĐƠN VỊ TUYỂN DỤNG" in _RUNTIME_RETRIEVAL_RULES
    assert "thuyết phục ứng viên ứng tuyển" in _RUNTIME_RETRIEVAL_RULES
    assert "tra search_knowledge theo dự án" in _RUNTIME_RETRIEVAL_RULES


@pytest.mark.parametrize("failed_stage", ["last_messages", "record_bot_pending"])
async def test_status_is_drained_when_preamble_fails(monkeypatch, failed_stage):
    entered = asyncio.Event()
    drained = asyncio.Event()
    svc, _ = _stub_svc(conv=_FakeConv())

    async def status(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()

    async def fail(*args, **kwargs):
        await entered.wait()
        raise RuntimeError("preamble failed")

    monkeypatch.setattr(runner, "_status_heartbeat", status)
    monkeypatch.setattr(svc, failed_stage, fail)
    with pytest.raises(RuntimeError, match="preamble failed"):
        await run_turn(_state(), _deps(_FakeZalo(), conversation=svc))
    assert drained.is_set()


async def test_status_is_drained_when_turn_is_cancelled_during_preamble(monkeypatch):
    entered = asyncio.Event()
    drained = asyncio.Event()
    svc, _ = _stub_svc(conv=_FakeConv())

    async def status(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()

    async def history(*args, **kwargs):
        await entered.wait()
        await asyncio.Event().wait()

    monkeypatch.setattr(runner, "_status_heartbeat", status)
    monkeypatch.setattr(svc, "last_messages", history)
    task = asyncio.create_task(run_turn(_state(), _deps(_FakeZalo(), conversation=svc)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert drained.is_set()


@pytest.mark.parametrize("terminal", ["answer", "send_failure", "empty", "error", "takeover"])
async def test_active_status_is_joined_before_answer_or_terminal(monkeypatch, terminal):
    entered = asyncio.Event()
    drained = asyncio.Event()
    active = False
    events = []

    class NativeSender(_FakeZalo):
        async def send_chat_action(self, chat_id, action):
            nonlocal active
            active = True
            events.append("typing")
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                active = False
                drained.set()

        async def send_message(self, chat_id, text):
            assert drained.is_set() and not active
            events.append("answer")
            return await super().send_message(chat_id, text)

    async def agent(*args, **kwargs):
        await entered.wait()
        if terminal == "error":
            raise RuntimeError("agent failed")
        return "" if terminal == "empty" else "Dự án đang tuyển công nhân."

    svc, _ = _stub_svc(conv=_FakeConv(), owned=terminal != "takeover")
    original_record = svc.record_bot_outcome

    async def record(*args, **kwargs):
        assert drained.is_set() and not active
        events.append("outcome")
        return await original_record(*args, **kwargs)

    monkeypatch.setattr(runner, "_agent_turn", agent)
    monkeypatch.setattr(svc, "record_bot_outcome", record)
    sender = NativeSender(results=[_SendResult(
        ok=False, error="provider unavailable", error_class="provider_error",
    )] if terminal == "send_failure" else None)
    outcome = await run_turn(_state(), _deps(sender, conversation=svc))
    assert drained.is_set() and not active
    assert events[0] == "typing"
    assert events[-1] == "outcome"
    expected = {"answer": "sent", "send_failure": "send_failed", "error": "error"}
    assert outcome["outcome"] == expected.get(terminal, "suppressed")
    calls = len(events)
    await asyncio.sleep(0.025)
    assert len(events) == calls


async def test_cancellation_joins_progressive_generation_and_status(monkeypatch):
    status_started = asyncio.Event()
    status_drained = asyncio.Event()
    agent_started = asyncio.Event()
    agent_drained = asyncio.Event()
    svc, _ = _stub_svc(conv=_FakeConv(), durable=True)

    async def status(*args, **kwargs):
        status_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            status_drained.set()

    async def agent(*args, **kwargs):
        await status_started.wait()
        agent_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            agent_drained.set()

    monkeypatch.setattr(runner, "_status_heartbeat", status)
    monkeypatch.setattr(runner, "_agent_turn", agent)
    task = asyncio.create_task(run_turn(_state(), _deps(
        _FakeZalo(), conversation=svc, progressive_send=True,
    )))
    await agent_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert status_drained.is_set()
    assert agent_drained.is_set()
    assert not svc.dispatched
    assert not any(
        pending.get_coro().__qualname__ == "Queue.get" for pending in asyncio.all_tasks()
    )


async def test_status_is_drained_before_first_progressive_answer(monkeypatch):
    status_started = asyncio.Event()
    status_drained = asyncio.Event()
    svc, _ = _stub_svc(conv=_FakeConv(), durable=True)
    prefix = "Dự án đang tuyển công nhân với thu nhập 9 triệu mỗi tháng. " * 5
    remainder = "Bạn cho mình số điện thoại để đăng ký ứng tuyển nhé."

    async def status(*args, **kwargs):
        status_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            status_drained.set()

    async def agent(*args, on_delta=None, **kwargs):
        await status_started.wait()
        await on_delta(prefix)
        await svc.early_dispatched.wait()
        assert status_drained.is_set()
        await on_delta(remainder)
        return prefix + remainder

    dispatch = svc.dispatch_outbound_message

    async def observed_dispatch(*args, **kwargs):
        assert status_drained.is_set()
        return await dispatch(*args, **kwargs)

    monkeypatch.setattr(runner, "_status_heartbeat", status)
    monkeypatch.setattr(runner, "_agent_turn", agent)
    monkeypatch.setattr(svc, "dispatch_outbound_message", observed_dispatch)
    outcome = await run_turn(_state(), _deps(
        _FakeZalo(), conversation=svc, progressive_send=True,
    ))
    assert outcome["outcome"] == "sent"
    assert len(svc.dispatched) == 2
    assert status_drained.is_set()


@pytest.mark.parametrize("gate", ["conversation", "runtime", "ownership"])
@pytest.mark.parametrize("exit_kind", ["return", "error", "cancel"])
async def test_setup_status_covers_initial_gates_and_is_drained_on_every_exit(
    monkeypatch, gate, exit_kind,
):
    started = asyncio.Event()
    drained = asyncio.Event()
    gate_entered = asyncio.Event()
    svc, _ = _stub_svc(conv=_FakeConv())
    state = _state()
    deps = _deps(_FakeZalo(), conversation=svc)

    async def inherited_status():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            drained.set()

    async def initial_gate(*args, **kwargs):
        await started.wait()
        assert not drained.is_set()
        gate_entered.set()
        if exit_kind == "error":
            raise RuntimeError("initial gate failed")
        if exit_kind == "cancel":
            await asyncio.Event().wait()
        return False if gate == "ownership" else None

    original_record = svc.record_bot_outcome

    async def record(*args, **kwargs):
        assert drained.is_set()
        return await original_record(*args, **kwargs)

    monkeypatch.setattr(svc, "record_bot_outcome", record)
    resolved_status = AsyncMock()
    monkeypatch.setattr(runner, "_status_heartbeat", resolved_status)
    if gate == "conversation":
        monkeypatch.setattr(svc, "get", initial_gate)
    elif gate == "runtime":
        state.runtime_revision_id = "revision"
        state.authority_generation = 1
        state.runtime_fingerprint = "fingerprint"
        deps.runtime_policy = SimpleNamespace(resolve_active_policy=initial_gate)
    else:
        state.lock_owner = "owner"
        monkeypatch.setattr(svc, "recheck_ownership", initial_gate)

    inherited = asyncio.create_task(inherited_status())
    deps.preamble_status_task = inherited
    turn = asyncio.create_task(run_turn(state, deps))
    await asyncio.wait_for(gate_entered.wait(), timeout=2)
    if exit_kind == "cancel":
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
    elif exit_kind == "error":
        with pytest.raises(RuntimeError, match="initial gate failed"):
            await turn
    else:
        outcome = await turn
        assert outcome["outcome"] in {"error", "suppressed"}
    assert inherited.done() and drained.is_set()
    assert deps.preamble_status_task is None
    resolved_status.assert_not_called()


async def test_status_handoff_joins_setup_request_before_resolved_sender_starts(monkeypatch):
    inherited_started = asyncio.Event()
    inherited_drained = asyncio.Event()
    resolved_started = asyncio.Event()
    resolved_drained = asyncio.Event()
    svc, _ = _stub_svc(conv=_FakeConv())
    deps = _deps(_FakeZalo(), conversation=svc)

    async def inherited_status():
        inherited_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            inherited_drained.set()

    original_get = svc.get

    async def get(*args, **kwargs):
        await inherited_started.wait()
        assert not inherited_drained.is_set()
        return await original_get(*args, **kwargs)

    async def resolved_status(*args, **kwargs):
        assert inherited_drained.is_set()
        resolved_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            resolved_drained.set()

    async def agent(*args, **kwargs):
        await resolved_started.wait()
        return "Dự án đang tuyển công nhân."

    original_send = deps.zalo.send_message

    async def send(*args, **kwargs):
        assert inherited_drained.is_set() and resolved_drained.is_set()
        return await original_send(*args, **kwargs)

    monkeypatch.setattr(svc, "get", get)
    monkeypatch.setattr(runner, "_status_heartbeat", resolved_status)
    monkeypatch.setattr(runner, "_agent_turn", agent)
    monkeypatch.setattr(deps.zalo, "send_message", send)
    deps.preamble_status_task = asyncio.create_task(inherited_status())
    outcome = await run_turn(_state(), deps)
    assert outcome["outcome"] == "sent"
    assert inherited_drained.is_set() and resolved_drained.is_set()


@pytest.mark.parametrize("provider", ["zalo_oa", "facebook_messenger"])
async def test_unsupported_native_status_providers_only_send_the_actual_answer(monkeypatch, provider):
    conv = _FakeConv(
        zalo_chat_id="oa:candidate" if provider == "zalo_oa" else None,
        zalo_channel="oa" if provider == "zalo_oa" else "bot",
        channel_identity=SimpleNamespace(provider=provider, external_id="candidate"),
    )
    svc, _ = _stub_svc(conv=conv, durable=True)
    sender = _FakeZalo()
    monkeypatch.setattr(runner, "_agent_turn", AsyncMock(return_value="Dự án đang tuyển công nhân."))
    status = AsyncMock()
    monkeypatch.setattr(runner, "_status_heartbeat", status)
    outcome = await run_turn(_state(), _deps(sender, conversation=svc))
    assert outcome["outcome"] == "sent"
    status.assert_not_called()
    assert len(svc.dispatched) == 1


def test_outbox_payload_attaches_media_per_self_checkin_topic():
    """Each how-to topic caption carries exactly its own screenshot.

    Only the exact approved captions on the TingTing OA account upgrade to a
    media payload — a paraphrase stays text, a caption with no image (tan-ca,
    general) stays text, and the same sentence on any other account stays text
    — so a sweep re-dispatch resends the same attachment without re-running the
    turn.
    """
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY
    from app.graph.dispatch import _account_key_for_conversation, _build_outbox_payload
    from app.graph.tingting_guide import TINGTING_SELF_CHECKIN_MEDIA

    class _Identity:
        account_key = TINGTING_OA_ACCOUNT_KEY

    class _Conv:
        channel_identity = _Identity()

    for caption, media in TINGTING_SELF_CHECKIN_MEDIA.items():
        payload = _build_outbox_payload(
            "oa:tingting:user-1",
            caption,
            "msg-inbound-1",
            account_key=_account_key_for_conversation(_Conv()),
        )
        assert payload["media_url"] == media["media_url"]
        assert payload["media_type"] == "image"
        assert payload["quote_message_id"] == "msg-inbound-1"

    paraphrase = _build_outbox_payload(
        "oa:tingting:user-1",
        "Mở app bấm tự chấm công nhé ạ",
        "m",
        account_key=TINGTING_OA_ACCOUNT_KEY,
    )
    assert "media_url" not in paraphrase
    other_account = _build_outbox_payload(
        "u", next(iter(TINGTING_SELF_CHECKIN_MEDIA)), "m", account_key="other-oa"
    )
    assert "media_url" not in other_account


@pytest.mark.parametrize(
    ("user_text", "sub_intent", "expected"),
    [
        ("cách bật định vị để chấm công", "how_to_gps", "TINGTING_SELF_CHECKIN_GPS_REPLY"),
        ("mấy giờ được bấm vào làm", "how_to_schedule", "TINGTING_SELF_CHECKIN_SCHEDULE_REPLY"),
        ("chấm công ở cổng nào", "how_to_gates", "TINGTING_SELF_CHECKIN_GATES_REPLY"),
        ("tan ca để làm gì", "how_to_tanca", "TINGTING_SELF_CHECKIN_TANCA_REPLY"),
    ],
)
@pytest.mark.asyncio
async def test_self_checkin_how_to_topics_return_their_fixed_line(
    monkeypatch, user_text, sub_intent, expected
):
    """Jev's sub-intent choice (inside the self_checkin gate) picks the line.

    Operator rule (2026-10-07): the old single punt caption is replaced by four
    per-topic lines — the lane returns the approved line directly off the Jev
    flags (no generation at all) and the send layer attaches the topic's
    screenshot to that exact caption on this account.
    """
    from app.graph.runner import _agent_turn
    from app.graph import tingting_guide

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "model reply"

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=user_text),
        deps,
        user_text,
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(
            intent="general", intent_confidence=0.2, self_checkin=True, self_checkin_intent=sub_intent
        ),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
        tingting_support_account=True,
    )

    assert reply == getattr(tingting_guide, expected)
    assert captured == {}  # fixed line: no generation at all


@pytest.mark.asyncio
async def test_self_checkin_general_intent_falls_through_to_the_model(monkeypatch):
    """A general how-to is composed from the persona knowledge, not a fixed line."""
    from app.graph.runner import _agent_turn
    from app.graph import tingting_guide

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "model reply"

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="tự chấm công là gì"),
        deps,
        "tự chấm công là gì",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(
            intent="general", intent_confidence=0.2, self_checkin=True, self_checkin_intent="how_to_general"
        ),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
        tingting_support_account=True,
    )

    assert reply == "model reply"
    assert captured != {}
    assert reply not in tingting_guide.TINGTING_SELF_CHECKIN_MEDIA


@pytest.mark.asyncio
async def test_self_checkin_toggle_intent_routes_to_the_employee_support_flow(monkeypatch):
    """enable/disable is a mutation: it reroutes and runs the agent with the tools.

    The turn takes the employee-support route (reason ``self_checkin_action``)
    BEFORE the clarify/hotline branch, so the agent lane runs with the three
    toggle tools bound (the reset pin narrows the registry to the TingTing
    toolset) instead of returning any fixed reply.
    """
    from app.graph.runner import _agent_turn
    from app.graph.runtime_policy import TINGTING_TOOL_NAMES

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "Đã gửi mã xác minh 6 số qua Zalo."

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    timings: dict = {"lane": "agent"}
    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="đăng ký tự chấm công cho em"),
        deps,
        "đăng ký tự chấm công cho em",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings=timings,
        decisions=TurnDecisions(
            intent="general", intent_confidence=0.2, self_checkin=True, self_checkin_intent="enable"
        ),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
        tingting_support_account=True,
    )

    assert reply == "Đã gửi mã xác minh 6 số qua Zalo."
    assert captured != {}  # the agent lane ran the flow
    assert set(captured["allowed_tools"]) == set(TINGTING_TOOL_NAMES)
    assert "send_self_checkin_otp" in captured["allowed_tools"]
    assert timings["route_reason"] == "self_checkin_action"
    assert timings["intent"] == "employee_support"


@pytest.mark.asyncio
async def test_self_checkin_branch_outranks_the_wage_wait_flag(monkeypatch):
    """A self-check-in phrasing can light both flags; the topic line wins."""
    from app.graph.runner import _agent_turn
    from app.graph.tingting_guide import (
        TINGTING_SELF_CHECKIN_SCHEDULE_REPLY,
        TINGTING_WAGE_WAIT_REPLY,
    )

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "model reply"

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="mấy giờ bấm vào làm"),
        deps,
        "mấy giờ bấm vào làm",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(
            intent="faq_detail",
            intent_confidence=0.9,
            wage_wait=True,
            self_checkin=True,
            self_checkin_intent="how_to_schedule",
        ),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
        tingting_support_account=True,
    )

    assert reply == TINGTING_SELF_CHECKIN_SCHEDULE_REPLY
    assert reply != TINGTING_WAGE_WAIT_REPLY
    assert captured == {}


@pytest.mark.asyncio
async def test_self_checkin_flag_is_inert_off_the_support_oa(monkeypatch):
    """The flag must not fire where the media rule cannot (identity gate).

    Off the support account there is no topic image to attach, so the turn
    runs the normal agent path instead of forcing TingTing-specific wording.
    """
    from app.graph.runner import _agent_turn
    from app.graph import tingting_guide

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "model reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "RECRUITMENT-PERSONA-MARKER", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=False),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="chấm công thế nào"),
        deps,
        "chấm công thế nào",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="general", intent_confidence=0.4, self_checkin=True),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=False,
        tingting_support_account=False,
    )

    assert reply == "model reply"
    assert reply not in tingting_guide.TINGTING_SELF_CHECKIN_MEDIA
    assert all(
        reply != getattr(tingting_guide, name)
        for name in (
            "TINGTING_SELF_CHECKIN_GPS_REPLY",
            "TINGTING_SELF_CHECKIN_SCHEDULE_REPLY",
            "TINGTING_SELF_CHECKIN_GATES_REPLY",
            "TINGTING_SELF_CHECKIN_TANCA_REPLY",
        )
    )
    assert captured != {}  # the agent ran its normal path


@pytest.mark.asyncio
async def test_login_trouble_outranks_the_self_checkin_flag(monkeypatch):
    """A login problem mid-message keeps the reset flow — the topic line is secondary.

    Both judgments can be true ("quên mật khẩu, không chấm công được"); the
    employee_support intent must win so the reset tools stay bound.
    """
    from app.graph.runner import _agent_turn
    from app.graph import tingting_guide

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "reset flow reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="quên mật khẩu, không chấm công được",
        ),
        deps,
        "quên mật khẩu, không chấm công được",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(
            intent="employee_support",
            intent_confidence=0.92,
            login_problem=True,
            self_checkin=True,
        ),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
        tingting_support_account=True,
    )

    assert reply == "reset flow reply"
    assert all(
        reply != getattr(tingting_guide, name)
        for name in (
            "TINGTING_SELF_CHECKIN_GPS_REPLY",
            "TINGTING_SELF_CHECKIN_SCHEDULE_REPLY",
            "TINGTING_SELF_CHECKIN_GATES_REPLY",
            "TINGTING_SELF_CHECKIN_TANCA_REPLY",
        )
    )
    assert captured != {}  # the reset flow ran, not a fixed topic line


@pytest.mark.asyncio
async def test_wage_wait_intent_forces_the_waiting_line_before_the_hotline(monkeypatch):
    """One payday intent, one answer: the waiting line beats the hotline branch.

    Operator rule (2026-10-06): "có lương chưa" used to be short-circuited to
    ``tingting_hotline_reply`` by a confident faq_detail reading — the lane
    answered WITHOUT the model ever running — while "ứng lương được chưa"
    fell through to the model and matched the payday prompt rule. The Jev
    ``wage_wait`` flag now forces the approved waiting line before that
    clarify/hotline branch, so both phrasings get the same answer.
    """
    from app.graph.runner import _agent_turn
    from app.graph.tingting_guide import TINGTING_WAGE_WAIT_REPLY

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "model reply"

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    # faq_detail at 0.95 is exactly the reading that used to hit the hotline
    # branch (not in _SUPPORT_CLARIFY_INTENTS, above the route floor).
    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="có lương chưa"),
        deps,
        "có lương chưa",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.95, wage_wait=True),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
        tingting_support_account=True,
    )

    assert reply == TINGTING_WAGE_WAIT_REPLY
    assert "chờ VFIC gửi dữ liệu tiền công" in reply
    assert captured == {}  # no generation, no hotline handoff


@pytest.mark.asyncio
async def test_wage_wait_flag_keeps_login_trouble_on_the_reset_flow(monkeypatch):
    """Login trouble outranks the payday flag — same precedence as self_checkin."""
    from app.graph.runner import _agent_turn
    from app.graph.tingting_guide import TINGTING_WAGE_WAIT_REPLY

    captured: dict[str, object] = {}

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "reset flow reply"

    async def _fake_build_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    class _Lead:
        async def context(self, *args, **kwargs):  # noqa: ARG002
            return "", ""

        def instruction(self, question):  # noqa: ARG002
            return ""

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.lead = _Lead()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=True),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(
            conversation_id=CONV_ID,
            version_at_start=1,
            user_text="quên mật khẩu, lương về chưa cho em biết",
        ),
        deps,
        "quên mật khẩu, lương về chưa cho em biết",
        provider="zalo_oa",
        chat_id="oa:user-1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(
            intent="employee_support",
            intent_confidence=0.9,
            login_problem=True,
            wage_wait=True,
        ),
        project_context=ProjectTurnContext(state="EXPLORE"),
        tingting_reset_allowed=True,
        tingting_support_account=True,
    )

    assert reply != TINGTING_WAGE_WAIT_REPLY
    assert reply == "reset flow reply"
    assert captured != {}


# ─── progressive remainder: the placeholder is created only when dispatched ──
#
# Regression pin for the orphaned "Đang soạn trả lời..." rows (42 between
# 2026-07-14 and 2026-10-06): a progressive turn whose REMAINDER was suppressed
# by grounding used to create the remainder's PENDING placeholder first and then
# exit without ever resolving it — the next turn's stale-pending sweep flipped
# it FAILED, and the CRM thread showed a dead "Gửi lỗi" bubble that was never a
# real message. Grounding now runs before the row is created.


def _progressive_fixture(*, remainder: str):
    from types import SimpleNamespace

    conv = SimpleNamespace(id="conv-1")
    state = SimpleNamespace(
        conversation_id="conv-1",
        trace_id=None,
        pending_message_id=42,
    )
    early = SimpleNamespace(
        raw="Phần một câu trả lời.",
        offset=len("Phần một câu trả lời."),
        text="Phần một câu trả lời.",
        message_id=42,
        outbox_id=900,
        send_result=SimpleNamespace(
            ok=True, msg_id="z-1", error=None, error_class=None, suppressed=False
        ),
    )
    stream = SimpleNamespace(
        raw=f"Phần một câu trả lời.{remainder}", evidence=[]
    )

    class _Svc:
        def __init__(self) -> None:
            self.pending_created = 0
            self.finalized: list[int] = []

        async def finalize_outbound_dispatch(self, _conv, **kwargs):  # noqa: ARG002
            self.finalized.append(kwargs.get("message_id"))

        async def record_bot_pending(self, _conv, **_kwargs):
            self.pending_created += 1
            return SimpleNamespace(id=555)

    return conv, state, early, stream, _Svc()


@pytest.mark.asyncio
async def test_suppressed_remainder_never_creates_its_placeholder_row(monkeypatch):
    """An ungrounded remainder is suppressed BEFORE its placeholder exists."""
    import app.graph.progressive as prog
    from app.graph.grounding import _UngroundedContact

    conv, state, early, stream, svc = _progressive_fixture(
        remainder=" Gọi ngay 0912345678 để được giữ vị trí."
    )

    def _ungrounded(*_args, **_kwargs):
        return _UngroundedContact(channels=("phone",))

    monkeypatch.setattr(prog, "ground_reply", _ungrounded)

    remainder, outcome = await prog._complete_progressive_prefix(
        early=early,
        stream=stream,
        full_text=stream.raw,
        state=state,
        deps=SimpleNamespace(),
        conv=conv,
        svc=svc,
        timings={},
        lock_owner=None,
        recipient_id=None,
        allowed_text="",
        started=0.0,
        outcome_label="agent",
        faq_metadata=None,
        manifest_policy=None,
        allow_recruitment_fast_lane=True,
        pending_kwargs={},
        t0=0.0,
    )

    assert remainder == ""
    assert outcome is None
    # The fix's whole point: no placeholder row for a dispatch that will never
    # happen — the next turn has nothing to flip to FAILED.
    assert svc.pending_created == 0
    # The delivered bubble itself was terminalized exactly once.
    assert svc.finalized == [42]


@pytest.mark.asyncio
async def test_live_remainder_creates_exactly_one_placeholder_after_grounding(
    monkeypatch,
):
    """A grounded remainder still gets its placeholder, created post-grounding."""
    import app.graph.progressive as prog

    conv, state, early, stream, svc = _progressive_fixture(
        remainder=" Ca ngày chạy từ 08:00 đến 20:00."
    )

    def _passthrough(text, *_args, **_kwargs):
        return text

    monkeypatch.setattr(prog, "ground_reply", _passthrough)

    remainder, outcome = await prog._complete_progressive_prefix(
        early=early,
        stream=stream,
        full_text=stream.raw,
        state=state,
        deps=SimpleNamespace(),
        conv=conv,
        svc=svc,
        timings={},
        lock_owner=None,
        recipient_id=None,
        allowed_text="",
        started=0.0,
        outcome_label="agent",
        faq_metadata=None,
        manifest_policy=None,
        allow_recruitment_fast_lane=True,
        pending_kwargs={},
        t0=0.0,
    )

    assert outcome is None
    assert remainder == " Ca ngày chạy từ 08:00 đến 20:00."
    assert svc.pending_created == 1
    assert state.pending_message_id == 555


@pytest.mark.asyncio
async def test_pleasantry_gets_a_smile_not_a_generation(monkeypatch):
    """A politeness-only message is acknowledged with an emoji, no model run.

    The 2026-10-06 incident: a bare "cam on" ran the full agent stack for 252
    seconds (37 LLM calls across the stacked repair layers) and shipped a
    degenerate answer that repeated its opener four times, while the
    candidate's follow-ups queued behind the chat lock. Jev's pleasantry
    judgment — a message that is ONLY a greeting/thanks/ack — now answers with
    the smile and never reaches the agent.
    """
    from app.graph.runner import _agent_turn
    from types import SimpleNamespace as _Msg

    class _FakeAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            self.calls += 1
            return "model reply"

    agent = _FakeAgent()
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = agent
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=False),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )
    # Prior bot traffic: the candidate has already been answered before, so
    # this is not a cold open.
    from app.models.conversation import MessageSender
    prior = [_Msg(sender=MessageSender.BOT)]

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="cam on"),
        deps,
        "cam on",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=prior,
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="small_talk", intent_confidence=0.95, pleasantry=True),
    )

    assert reply == lanes.POLITE_ACK_REPLY == "😊"
    assert agent.calls == 0


@pytest.mark.asyncio
async def test_pleasantry_ack_never_fires_on_a_content_answer(monkeypatch):
    """A short answer to the bot's own question runs the agent, not a smile.

    The 2026-10-08 incident: "Đồng triều ạ" answered the bot's "anh/chị ở
    thành phố/thị xã nào của Quảng Ninh?" — but Jev's probabilistic pleasantry
    vote scored it above the gate and the lane shipped a bare "😊" while the
    candidate waited for the bus-route check. ``is_known_pleasantry`` is the
    fail-closed backstop: a message that is not a KNOWN pleasantry form never
    acks, whatever Jev said.
    """
    from app.graph.runner import _agent_turn
    from types import SimpleNamespace as _Msg

    class _FakeAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            self.calls += 1
            return "Dạ Đồng Triều thì em kiểm tra tuyến xe ngay ạ."

    agent = _FakeAgent()
    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = agent
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=False),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )
    from app.models.conversation import MessageSender
    prior = [_Msg(sender=MessageSender.BOT, body="Anh/chị ở thị xã nào của Quảng Ninh?")]

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="Đồng triều ạ"),
        deps,
        "Đồng triều ạ",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=prior,
        timings={"lane": "agent"},
        decisions=TurnDecisions(
            intent="profile_update", intent_confidence=0.7, pleasantry=True
        ),
    )

    assert reply == "Dạ Đồng Triều thì em kiểm tra tuyến xe ngay ạ."
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_pleasantry_ack_never_fires_on_a_cold_open(monkeypatch):
    """A bare "hi" as the FIRST message keeps the greeting flow, not a smile."""
    from app.graph.runner import _agent_turn

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            return "Dạ em chào anh ạ."

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=False),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="hi"),
        deps,
        "hi",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={"lane": "agent"},
        decisions=TurnDecisions(intent="small_talk", intent_confidence=0.9, pleasantry=True),
    )

    assert reply == "Dạ em chào anh ạ."


@pytest.mark.asyncio
async def test_pleasantry_ack_keeps_contact_info_on_the_workflow(monkeypatch):
    """A message carrying contact info is workflow input, never just a smile."""
    from app.graph.runner import _agent_turn

    class _FakeAgent:
        async def agent(self, user_text, **kwargs):  # noqa: ARG002
            return "Dạ em đã nhận số của anh rồi ạ."

    deps = _deps(_FakeZalo(), conversation=object())
    deps.agent = _FakeAgent()
    deps.retrieval = SimpleNamespace(
        tingting_api_configured=AsyncMock(return_value=False),
        tingting_hotline=AsyncMock(return_value="+84 914 827 988"),
    )
    monkeypatch.setattr(
        lanes, "build_agent_user_text", lambda **kwargs: kwargs["current_user_text"]
    )
    from types import SimpleNamespace as _Msg
    from app.models.conversation import MessageSender
    prior = [_Msg(sender=MessageSender.BOT)]

    reply = await _agent_turn(
        BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="dạ đây 0356631024"),
        deps,
        "dạ đây 0356631024",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=prior,
        timings={"lane": "agent"},
        decisions=TurnDecisions(
            intent="general", intent_confidence=0.8, pleasantry=True, contact_info=True
        ),
    )

    assert reply == "Dạ em đã nhận số của anh rồi ạ."
