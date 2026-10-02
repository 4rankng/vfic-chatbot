"""The LLM authors every candidate-facing reply (invariant).

End state of the "one author" refactor: the only text that can reach
``zalo.sent`` is either ``MiniMaxAgent.agent``'s own prose or the empty string
(suppression). Every retired seam now hands the model evidence or a mandatory
instruction and lets it write the reply:

* project clarification — a mandatory route hint, not a code-built question;
* out-of-scope handoff — a routing instruction naming the fixed-facts hotline;
* income authority (prefetch and in-round) — the verified render as evidence;
* tool-loop exhaustion — one final tool-free composition round;
* contact veto — one model rewrite round (a second violation suppresses).

The two operator-approved TingTing verbatim returns (``lanes.py``) are the sole
exceptions and are covered elsewhere. These tests drive each seam and assert the
delivered reply is the scripted model output, never a canned constant.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.timeout(30)


class _ScriptedLLM:
    """Scripted responses: a string is final prose; a list is tool calls."""

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.calls = 0
        self.model_name = "scripted-model"

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, _messages, **_kwargs):
        from langchain_core.messages import AIMessage

        self.calls += 1
        if not self._replies:
            return AIMessage(content="")
        entry = self._replies.pop(0)
        if isinstance(entry, str):
            return AIMessage(content=entry)
        return AIMessage(content="", tool_calls=entry)

    async def astream(self, messages, **kwargs):
        from langchain_core.messages import AIMessageChunk

        message = await self.ainvoke(messages, **kwargs)
        yield AIMessageChunk(
            content=message.content,
            tool_call_chunks=[
                {
                    "name": call["name"],
                    "args": json.dumps(call.get("args", {})),
                    "id": call.get("id") or f"call-{index}",
                    "index": index,
                }
                for index, call in enumerate(getattr(message, "tool_calls", None) or [])
            ],
        )


class _FakeRetrieval:
    async def list_active_projects(self):
        return []

    async def match_documents(self, *_args, **_kwargs):
        return []

    async def match_memories(self, *_args, **_kwargs):
        return []

    async def income_summary_for_active_projects(self, *_args, **_kwargs):
        return []

    async def project_id_by_slug(self, *_args, **_kwargs):
        return "fake-pid"


# --- income authority: prefetch and in-round --------------------------------


@pytest.mark.asyncio
async def test_income_prefetch_evidence_is_composed_by_the_model(monkeypatch):
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    payload = (
        'COMPARE_INCOME_JSON={"status":"matched","target_monthly_vnd":20000000,'
        '"projects":[{"project_slug":"rorze","project_name":"Rorze","evidence":['
        '{"feature_key":"take_home_income","name_vi":"Thu nhập","value_text":'
        '"14-15 triệu/tháng chưa gồm thưởng"}'
        ']}],"safe_reply":"Với mốc 20 triệu/tháng, dữ liệu thu nhập đã xác minh là:\\n'
        '- Rorze:\\n  • Thu nhập: 14-15 triệu/tháng chưa gồm thưởng."}'
    )

    async def fake_dispatch(_retrieval, _embedder, _name, _args, **_kwargs):
        return payload

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    model_text = "Dạ với mốc 20 triệu, Rorze có thu nhập 14-15 triệu/tháng chưa gồm thưởng ạ."
    llm = _ScriptedLLM([model_text])

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=3).agent(
        "lương 20 triệu",
        system="sys",
        retrieval=_FakeRetrieval(),
        embedder=None,
        allowed_tools=("compare_income",),
        lookup_query="lương 20 triệu",
        required_tool="compare_income",
        required_tool_args={"target_monthly_vnd": 20_000_000},
    )

    assert reply == model_text
    assert llm.calls == 1
    # The verified render is only ever evidence, never the delivered answer.
    assert reply != "Với mốc 20 triệu/tháng, dữ liệu thu nhập đã xác minh là:"


@pytest.mark.asyncio
async def test_income_in_round_evidence_is_composed_by_the_model(monkeypatch):
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    safe_reply = (
        "Với mốc 20.5 triệu/tháng, dữ liệu thu nhập đã xác minh là:\n"
        "- Rorze:\n  • Thu nhập: 20.5-21 triệu/tháng bình quân năm gồm thưởng."
    )
    payload = (
        'COMPARE_INCOME_JSON={"status":"matched","target_monthly_vnd":20500000,'
        '"projects":[{"project_name":"Rorze","evidence":[{"name_vi":"Thu nhập",'
        '"value_text":"20.5-21 triệu/tháng bình quân năm gồm thưởng."}]}],'
        f'"safe_reply":{json.dumps(safe_reply, ensure_ascii=False)}}}'
    )
    calls = 0

    async def fake_dispatch(_retrieval, _embedder, _name, _args, **_kwargs):
        nonlocal calls
        calls += 1
        return "Không có dữ liệu phù hợp." if calls == 1 else payload

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    llm = _ScriptedLLM(
        [[{"name": "compare_income", "args": {}, "id": "c1"}], safe_reply]
    )

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=3).agent(
        "lương 20.5 triệu",
        system="sys",
        retrieval=_FakeRetrieval(),
        embedder=None,
        allowed_tools=("compare_income",),
        required_tool="compare_income",
        required_tool_args={"target_monthly_vnd": 20_500_000},
    )

    assert reply == safe_reply
    assert llm.calls == 2  # tool round + tool-free composition round


# --- tool-loop exhaustion ----------------------------------------------------


@pytest.mark.asyncio
async def test_tool_loop_exhaustion_ships_model_prose(monkeypatch):
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def fake_dispatch(_retrieval, _embedder, _name, _args, **_kwargs):
        return '{"ACTIVE_PROJECT_LOOKUP": {"projects": [{"id": "project-7"}]}}'

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    model_text = "Dạ hiện em chưa tra được thông tin, anh/chị thử lại sau nhé."
    llm = _ScriptedLLM([[{"name": "list_active_projects", "args": {}, "id": "c"}]] * 2 + [model_text])
    metrics: dict = {}

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=2).agent(
        "bên mình còn tuyển không?",
        system="sys",
        retrieval=_FakeRetrieval(),
        embedder=None,
        metrics=metrics,
    )

    assert reply == model_text
    assert metrics["tool_loop_exhausted"] is True


# --- contact veto becomes a repair round ------------------------------------


@pytest.mark.asyncio
async def test_contact_veto_is_repaired_by_one_model_rewrite():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    invented = "Anh/chị gọi hotline nội bộ 0999888777 để được hỗ trợ ạ."
    repaired = "Dạ anh/chị để lại số điện thoại, em kiểm tra rồi liên hệ lại ngay ạ."
    llm = _ScriptedLLM([invented, repaired])

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=3).agent(
        "cần hỗ trợ tài khoản",
        system="Liên hệ VFIC: 1800 7228",
        retrieval=_FakeRetrieval(),
        embedder=None,
    )

    assert reply == repaired
    assert llm.calls == 2
    assert "0999888777" not in reply


@pytest.mark.asyncio
async def test_contact_veto_suppresses_on_a_second_violation():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    invented = "Anh/chị gọi hotline nội bộ 0999888777 để được hỗ trợ ạ."
    llm = _ScriptedLLM([invented, invented])

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=3).agent(
        "cần hỗ trợ tài khoản",
        system="Liên hệ VFIC: 1800 7228",
        retrieval=_FakeRetrieval(),
        embedder=None,
    )

    assert reply == ""
    assert llm.calls == 2  # one repair attempt, then suppression


# --- lane seams: clarification and out-of-scope -----------------------------


@pytest.mark.asyncio
async def test_project_clarification_is_a_mandatory_instruction_to_the_client():
    from app.graph.lanes import _resolve_lane
    from app.graph.ports import TurnDecisions

    captured: dict = {}

    class _LaneAgent:
        async def __call__(self, state, deps, user_text, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            return "**Bạn muốn hỏi Rorze hay LG Display?**"

    conv = SimpleNamespace(channel_identity=SimpleNamespace(provider="zalo_bot", account_key=""))
    project_context = SimpleNamespace(
        clarification="Bạn đang muốn hỏi dự án nào: Rorze, LG Display?",
        clarification_projects=("Rorze", "LG Display"),
        direct_context=None,
        state="EXPLORE",
        knowledge_mode=None,
    )

    resolution = await _resolve_lane(
        state=SimpleNamespace(conversation_id="c1", user_text="Rorze ở đâu?"),
        deps=SimpleNamespace(),
        conv=conv,
        svc=object(),
        decisions=TurnDecisions(intent="general", intent_confidence=0.9),
        turn_route=SimpleNamespace(intent="general", reason="faq", confidence=0.9),
        project_context=project_context,
        recent_messages=[],
        manifest_policy=None,
        provider="zalo_bot",
        recipient_id="z1",
        timings={},
        started=None,
        lock_owner=None,
        status_task=None,
        t0=0.0,
        agent_turn=_LaneAgent(),
    )

    assert resolution.lane == "agent"
    assert resolution.candidate == "**Bạn muốn hỏi Rorze hay LG Display?**"
    instruction = captured["mandatory_instruction"]
    assert "PHẢI hỏi lại ứng viên muốn hỏi dự án nào" in instruction
    assert "Rorze, LG Display" in instruction


@pytest.mark.asyncio
async def test_out_of_scope_reply_is_authored_by_the_model():
    from app.graph.lanes import _agent_turn
    from app.graph.ports import TurnDecisions

    captured: dict = {}
    model_text = "Dạ phần này em chưa hỗ trợ được. Anh/chị gọi hotline 1800 7228 nhé ạ."

    class _Agent:
        async def agent(self, user_text, **kwargs):
            captured["user_text"] = user_text
            captured["system"] = kwargs.get("system", "")
            return model_text

    deps = SimpleNamespace(
        agent=_Agent(),
        retrieval=object(),
        embedder=object(),
        make_retrieval=None,
        lead=None,
    )

    reply = await _agent_turn(
        SimpleNamespace(conversation_id="c1"),
        deps,
        "mua thuốc ở đâu",
        provider="zalo_bot",
        chat_id="z1",
        recent_messages=[],
        timings={},
        decisions=TurnDecisions(intent="out_of_scope", intent_confidence=0.9),
    )

    assert reply == model_text
    assert captured != {}
    # The hotline is an instruction (fixed facts + route hint), never a constant.
    assert "SỰ THẬT CỐ ĐỊNH" in captured["user_text"]
