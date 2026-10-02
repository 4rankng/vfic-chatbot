"""Lane-level tests: the unevidenced-absence self-check in ``lanes._agent_turn``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.graph.lanes import _absence_self_check
from app.graph.router import TurnRoute

pytestmark = pytest.mark.timeout(30)

ABSENCE_DRAFT = "Dạ hiện chưa có dự án nào làm việc tại VSIP ạ."
AMTRAN_REPLY = (
    "Dạ bên em CÓ dự án làm việc tại KCN VSIP Thủy Nguyên, đó là AMTRAN ạ. "
    "Anh/chị cho em xin số điện thoại để chuyên viên gọi lại tư vấn nhé ạ?"
)


def _route(intent: str = "recommend") -> TurnRoute:
    return TurnRoute(intent, "agent", reason="fallback", confidence=0.27)


def _kwargs() -> dict:
    return {
        "system": "sys",
        "retrieval": SimpleNamespace(),
        "embedder": None,
        "allowed_tools": ("search_knowledge", "search_bus_timetable"),
        "use_fast": False,
        "make_retrieval": None,
        "lookup_query": "gần núi đèo là vsip chứ",
        "metrics": {"tool_breakdown": {"search_knowledge": 1161}},
    }


class _FakeAgent:
    """Scripted agent: pops one reply per call, records every call."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict]] = []

    async def agent(self, text: str, **kwargs: dict) -> str:
        self.calls.append((text, kwargs))
        if not self.replies:
            return ""
        return self.replies.pop(0)


def _deps(agent: _FakeAgent) -> SimpleNamespace:
    class _HotlineRetrieval:
        async def tingting_hotline(self) -> str:
            return "1800 7228"

    return SimpleNamespace(
        agent=agent,
        retrieval=_HotlineRetrieval(),
        embedder=None,
        make_retrieval=None,
    )


def _check_args(
    agent: _FakeAgent,
    reply: str,
    timings: dict,
    *,
    intent: str = "recommend",
    registry: frozenset[str] | None = None,
    tingting_reset_allowed: bool = False,
) -> dict:
    agent_kwargs = {**_kwargs(), "resolved_tool_registry": registry}
    agent_kwargs["metrics"] = timings
    return dict(
        deps=_deps(agent),
        reply=reply,
        route=_route(intent),
        agent_kwargs=agent_kwargs,
        timings=timings,
        system="sys",
        user_text="gần núi đèo là vsip chứ",
        chat_id="chat-1",
        recent_messages=[],
        lead_profile="",
        lead_collection_instruction="",
        tingting_reset_allowed=tingting_reset_allowed,
        tingting_support_account=False,
    )


@pytest.mark.asyncio
async def test_unevidenced_absence_gets_one_catalog_self_check() -> None:
    agent = _FakeAgent([AMTRAN_REPLY])
    timings: dict = {"tool_breakdown": {"search_knowledge": 1161}}
    reply = await _absence_self_check(
        **_check_args(agent, ABSENCE_DRAFT, timings)
    )
    assert reply == AMTRAN_REPLY
    assert timings["absence_guard"] == "retry_verified"
    assert len(agent.calls) == 1
    text, kwargs = agent.calls[0]
    assert "LƯU Ý BẮT BUỘC" in text
    assert "hotline 1800 7228" in text
    assert kwargs["required_tool"] == "list_active_projects"
    assert set(kwargs["allowed_tools"]) == {
        "list_active_projects",
        "search_knowledge",
    }
    assert "forced_project_slug" not in kwargs
    assert "on_delta" not in kwargs
    assert "on_evidence" not in kwargs
    assert kwargs["metrics"] is timings


@pytest.mark.asyncio
async def test_evidenced_absence_ships_unchanged() -> None:
    agent = _FakeAgent([ABSENCE_DRAFT])
    timings = {"tool_call_counts": {"list_active_projects": 1}}
    reply = await _absence_self_check(
        **_check_args(agent, ABSENCE_DRAFT, timings)
    )
    assert reply == ABSENCE_DRAFT
    assert "absence_guard" not in timings
    assert agent.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "intent"),
    [
        ("AMTRAN chưa có ký túc xá ạ.", "recommend"),
        (ABSENCE_DRAFT, "timetable"),
        (ABSENCE_DRAFT, "small_talk"),
    ],
)
async def test_out_of_scope_claims_ship_unchanged(reply: str, intent: str) -> None:
    agent = _FakeAgent([ABSENCE_DRAFT])
    timings: dict = {"tool_breakdown": {"search_knowledge": 1161}}
    result = await _absence_self_check(
        **_check_args(agent, reply, timings, intent=intent)
    )
    assert result == reply
    assert agent.calls == []
    assert "absence_guard" not in timings


@pytest.mark.asyncio
async def test_tingting_support_turns_never_retry() -> None:
    agent = _FakeAgent([ABSENCE_DRAFT])
    timings: dict = {}
    result = await _absence_self_check(
        **_check_args(
            agent,
            ABSENCE_DRAFT,
            timings,
            tingting_reset_allowed=True,
        )
    )
    assert result == ABSENCE_DRAFT
    assert agent.calls == []


@pytest.mark.asyncio
async def test_empty_retry_suppresses_the_turn() -> None:
    agent = _FakeAgent([""])
    timings: dict = {"tool_breakdown": {"search_knowledge": 1161}}
    result = await _absence_self_check(
        **_check_args(agent, ABSENCE_DRAFT, timings)
    )
    assert result == ""
    assert timings["absence_guard"] == "retry_suppressed"


@pytest.mark.asyncio
async def test_hedge_form_retry_marks_hedged() -> None:
    hedge = (
        "Theo dữ liệu hiện tại em chưa tìm thấy dự án nào ở khu vực đó ạ. "
        "Anh/chị gọi hotline 1800 7228 để chuyên viên hỗ trợ thêm nhé ạ."
    )
    agent = _FakeAgent([hedge])
    timings: dict = {"tool_breakdown": {"search_knowledge": 1161}}
    result = await _absence_self_check(
        **_check_args(agent, ABSENCE_DRAFT, timings)
    )
    assert result == hedge
    assert timings["absence_guard"] == "hedged"


@pytest.mark.asyncio
async def test_registry_without_catalog_falls_back_to_hedge() -> None:
    agent = _FakeAgent([
        "Theo dữ liệu hiện tại em chưa tìm thấy dự án nào ạ, "
        "anh/chị gọi hotline 1800 7228 giúp em nhé ạ."
    ])
    timings: dict = {"tool_breakdown": {"search_knowledge": 1161}}
    result = await _absence_self_check(
        **_check_args(
            agent,
            ABSENCE_DRAFT,
            timings,
            registry=frozenset({"search_knowledge"}),
        )
    )
    assert "Theo dữ liệu hiện tại" in result
    assert timings["absence_guard"] == "hedged"
    text, kwargs = agent.calls[0]
    assert kwargs["allowed_tools"] is None
    assert kwargs["resolved_tool_registry"] == frozenset()


@pytest.mark.asyncio
async def test_kill_switch_disables_the_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ABSENCE_GUARD_ENABLED", "false")
    agent = _FakeAgent([ABSENCE_DRAFT])
    timings: dict = {"tool_breakdown": {"search_knowledge": 1161}}
    result = await _absence_self_check(
        **_check_args(agent, ABSENCE_DRAFT, timings)
    )
    assert result == ABSENCE_DRAFT
    assert agent.calls == []


@pytest.mark.asyncio
async def test_dispatch_counts_are_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("langchain_core")
    from langchain_core.messages import AIMessage

    from app.graph.clients import MiniMaxAgent

    class _LLM:
        model_name = "scripted"

        def __init__(self) -> None:
            self._called = False

        def bind_tools(self, _tools, **_kwargs):
            return self

        async def ainvoke(self, _messages, **_kwargs):
            if not self._called:
                self._called = True
                return AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "list_active_projects", "args": {}, "id": "c1"}
                    ],
                )
            return AIMessage(content="Dạ ạ.")

    class _Retrieval:
        async def list_active_projects(self):
            return []

    async def fake_dispatch(_retrieval, _embedder, _name, _args, **_kwargs):
        return '{"ACTIVE_PROJECT_LOOKUP": {"projects": []}}'

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    metrics: dict = {}

    await MiniMaxAgent(_LLM(), embedder=None, max_iters=3).agent(
        "còn dự án nào ở vsip?",
        system="sys",
        retrieval=_Retrieval(),
        embedder=None,
        allowed_tools=("list_active_projects",),
        metrics=metrics,
    )

    assert metrics["tool_call_counts"]["list_active_projects"] == 1
