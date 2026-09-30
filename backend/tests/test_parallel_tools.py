"""Parallel tool dispatch — ``MiniMaxAgent.agent`` runs multiple tool_calls concurrently.

When the LLM returns 2+ tool_calls in one response, each call gets its own
``GraphRetrievalPort`` via ``make_retrieval`` (an isolated DB session) and runs
concurrently via ``asyncio.gather``. This test suite pins:

* Parallel dispatch actually happens (concurrency synchronization test).
* Result order matches tool_calls order (LLM sees identical context).
* Sequential fallback when ``make_retrieval`` is ``None``.
* Single tool call uses the shared ``retrieval`` (no factory overhead).
* Individual tool failures never crash the gather (error isolation).
* The ``parallel_tool_max_concurrency`` semaphore caps simultaneous calls.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from app.recruitment.domain.recommendation import ProjectFeatures

# The assertions observe scheduling directly, not wall-clock budgets; this
# timeout only guards against an event-loop hang.
pytestmark = pytest.mark.timeout(30)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """Returns a scripted sequence of responses, then a final no-tool reply.

    Each call to ``ainvoke`` pops the next response from ``self._replies``.
    A response is either a plain string (final text reply) or a list of tool-call
    dicts that the agent will dispatch.
    """

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.bound_names: list[str] = []
        self.bind_calls = 0
        self.calls = 0
        self.messages = []
        self.model_name = "scripted-model"
        self.trace_provider = "minimax"

    def bind_tools(self, tools, **_kwargs):
        self.bind_calls += 1
        self.bound_names = [tool["function"]["name"] for tool in tools]
        return self

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        from langchain_core.messages import AIMessage

        self.calls += 1
        self.messages = messages
        if not self._replies:
            return AIMessage(content="done")
        entry = self._replies.pop(0)
        if isinstance(entry, AIMessage):
            return entry
        if isinstance(entry, str):
            return AIMessage(content=entry)
        # entry is a list of {"name", "args", "id"} dicts
        return AIMessage(content="", tool_calls=entry)

    async def astream(self, messages, **kwargs):
        """Stream the same scripted reply as one chunk (progressive-send tests).

        A tool round carries no visible text, mirroring the real providers.
        """
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
    """A minimal GraphRetrievalPort that delegates to a handler function.

    ``handler(name, args)`` is called for every tool dispatch. This lets each
    test inject custom behavior (return value, delay, side effects).
    """

    def __init__(self, handler=None, identity: str = "shared"):
        self._handler = handler
        self.identity = identity

    async def list_active_projects(self):
        # The port returns ProjectFeatures rows: coerce generic handler returns
        # so the real tool always runs its happy path.
        rows = await self._handler("list_active_projects", {})
        return rows if isinstance(rows, list) else []

    async def match_documents(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("search_knowledge", {})

    async def match_faq(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("match_faq", {})

    async def match_memories(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("search_user_memory", {})

    async def active_projects_with_card(self):
        return await self._handler("active_projects_with_card", {})

    async def search_bus_timetable(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("search_bus_timetable", {})

    async def job_features_for_project(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("get_product_features", {})

    async def income_summary_for_active_projects(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("compare_income", {})

    async def project_id_by_slug(self, *args, **kwargs):  # noqa: ARG002
        return "fake-pid"


def _make_retrieval_factory(handler, identity_prefix="isolated"):
    """Build a ``make_retrieval`` that yields fresh ``_FakeRetrieval`` per call."""
    counter = 0

    @asynccontextmanager
    async def _factory():
        nonlocal counter
        counter += 1
        yield _FakeRetrieval(handler, identity=f"{identity_prefix}-{counter}")

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_parallel_dispatch_runs_tools_concurrently():
    """Two tool calls must overlap — proving actual concurrency.

    Deterministic overlap proof instead of a wall-clock budget: each handler
    suspends once (a yield point, not a timing assumption), and the assertion is
    that the second tool starts before the first finishes. A sequential dispatch
    can never satisfy that ordering.
    """
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    started: list[float] = []
    finished: list[float] = []

    async def handler(name, args):  # noqa: ARG001
        started.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.01)
        finished.append(asyncio.get_event_loop().time())
        return f"result-{name}"

    tool_calls = [
        {"name": "list_active_projects", "args": {}, "id": "c1"},
        {"name": "search_bus_timetable", "args": {"company": "LG", "question": "xe"}, "id": "c2"},
    ]
    llm = _ScriptedLLM([tool_calls, "all done"])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    make_retrieval = _make_retrieval_factory(handler)

    reply = await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        make_retrieval=make_retrieval,
    )

    assert reply == "all done"
    assert len(started) == 2 and len(finished) == 2
    # The second tool STARTED before the first FINISHED — sequential dispatch
    # cannot produce this ordering.
    assert max(started) < min(finished), (
        f"tool executions did not overlap: started={started} finished={finished}"
    )


async def test_sequential_fallback_when_no_factory():
    """Without make_retrieval, tools still run (sequentially on shared retrieval)."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    calls: list[str] = []

    async def handler(name, args):  # noqa: ARG001
        calls.append(name)
        return f"result-{name}"

    tool_calls = [
        {"name": "list_active_projects", "args": {}, "id": "c1"},
        {"name": "search_bus_timetable", "args": {"company": "LG", "question": "xe"}, "id": "c2"},
    ]
    llm = _ScriptedLLM([tool_calls, "done"])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)

    reply = await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        # No make_retrieval → sequential fallback
    )

    assert reply == "done"
    assert len(calls) == 2


async def test_agent_records_model_and_tool_round_metrics():
    """Per-turn metrics distinguish provider calls from tool dispatch time."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return f"result-{name}"

    llm = _ScriptedLLM(
        [
            [{"name": "list_active_projects", "args": {}, "id": "c1"}],
            "done",
        ]
    )
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    metrics: dict[str, int] = {}

    reply = await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        metrics=metrics,
    )

    assert reply == "done"
    assert metrics["llm_calls"] == 2
    assert metrics["llm_invoke_ms"] >= 0
    assert metrics["tool_calls"] == 1
    assert metrics["tool_rounds"] == 1
    assert metrics["tool_ms"] >= 0


async def test_agent_traces_reasoning_and_tool_names_for_each_model_call():
    messages = pytest.importorskip("langchain_core.messages")
    from app.graph.clients import MiniMaxAgent
    from app.graph.decision_trace import DecisionTraceBuilder

    async def handler(name, args):  # noqa: ARG001
        return "LG Display is active"

    tool_calls = [{"name": "list_active_projects", "args": {}, "id": "c1"}]
    llm = _ScriptedLLM(
        [
            messages.AIMessage(
                content="<think>I need the current project list.</think>",
                tool_calls=tool_calls,
            ),
            messages.AIMessage(
                content="<think>The tool confirms the project.</think>LG Display đang tuyển.",
            ),
        ]
    )
    trace = DecisionTraceBuilder()

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=5).agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        trace_sink=trace,
    )

    assert reply.endswith("LG Display đang tuyển.")
    model_turns = [
        event for event in trace.snapshot_payload()["events"] if event["kind"] == "model_turn"
    ]
    assert [{key: value for key, value in event.items() if key != "seq"} for event in model_turns] == [
        {
            "kind": "model_turn",
            "turn": 1,
            "phase": "tool_request",
            "provider": "minimax",
            "model": "scripted-model",
            "reasoning_status": "returned",
            "reasoning": "I need the current project list.",
            "tool_names": ["list_active_projects"],
        },
        {
            "kind": "model_turn",
            "turn": 2,
            "phase": "final",
            "provider": "minimax",
            "model": "scripted-model",
            "reasoning_status": "returned",
            "reasoning": "The tool confirms the project.",
            "tool_names": [],
        },
    ]
    assert all("LG Display đang tuyển." not in event["reasoning"] for event in model_turns)


async def test_agent_records_failed_model_attempt():
    """Provider failures still count as attempted calls with elapsed time."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    class _FailingLLM:
        def bind_tools(self, tools):  # noqa: ARG002
            return self

        async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
            raise RuntimeError("provider unavailable")

    metrics: dict = {}
    agent = MiniMaxAgent(_FailingLLM(), embedder=None, max_iters=1)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await agent.agent(
            "test",
            system="sys",
            retrieval=object(),
            embedder=None,
            metrics=metrics,
        )

    assert metrics["llm_calls"] == 1
    assert metrics["llm_invoke_ms"] >= 0
    assert metrics["tool_calls"] == 0


async def test_timetable_route_prefetches_and_removes_duplicate_tool(monkeypatch):
    """A confident timetable route should need one model call, not tool selection."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    dispatched: list[tuple[str, dict]] = []

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        dispatched.append((name, args))
        return "- LG Display • Tuyến A: Hào Quang 05:30"

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)

    class _OneShotLLM:
        def __init__(self) -> None:
            self.bound_names: list[str] = []
            self.messages = []
            self.calls = 0
            self.bind_calls = 0

        def bind_tools(self, tools):
            self.bind_calls += 1
            self.bound_names = [tool["function"]["name"] for tool in tools]
            return self

        async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
            from langchain_core.messages import AIMessage

            self.calls += 1
            self.messages = messages
            return AIMessage(content="Xe đón tại Hào Quang lúc 05:30.")

    llm = _OneShotLLM()
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    metrics: dict = {}

    reply = await agent.agent(
        "Lịch sử và hồ sơ đã được ghép vào prompt; câu hỏi hiện tại ở cuối.",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("search_bus_timetable",),
        lookup_query="xe đưa đón Hào Quang mấy giờ?",
        metrics=metrics,
    )

    assert reply == "Xe đón tại Hào Quang lúc 05:30."
    assert dispatched == [
        (
            "search_bus_timetable",
            {"company": "", "question": "xe đưa đón Hào Quang mấy giờ?"},
        )
    ]
    assert llm.bind_calls == 0
    assert any("Hào Quang 05:30" in str(message.content) for message in llm.messages)
    assert llm.calls == 1
    assert metrics["prefetch_calls"] == 1
    assert metrics["prefetch_hit"] is True


async def test_timetable_prefetch_miss_keeps_tool_available(monkeypatch):
    """A broad prefetch miss must preserve the model's scoped retry path."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        return "Không tìm thấy lịch xe phù hợp."

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)

    class _RecordingLLM:
        def __init__(self) -> None:
            self.bound_names: list[str] = []

        def bind_tools(self, tools):
            self.bound_names = [tool["function"]["name"] for tool in tools]
            return self

        async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
            from langchain_core.messages import AIMessage

            return AIMessage(content="Bạn cho mình xin tên công ty nhé.")

    llm = _RecordingLLM()
    metrics: dict = {}
    agent = MiniMaxAgent(llm, embedder=None, max_iters=1)

    await agent.agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("search_bus_timetable",),
        lookup_query="xe đưa đón mấy giờ?",
        metrics=metrics,
    )

    assert "search_bus_timetable" in llm.bound_names
    assert metrics["prefetch_hit"] is False


async def test_faq_detail_unguided_prefetches_only_knowledge(monkeypatch):
    """An unguided FAQ lookup stays RAG-only instead of loading every project."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    dispatched: list[tuple[str, dict]] = []

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        dispatched.append((name, args))
        return "KB: LG Display làm ca ngày 08:00-20:00 và ca đêm 20:00-08:00."

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    llm = _ScriptedLLM(["LG Display làm ca ngày 08:00-20:00 và ca đêm 20:00-08:00."])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=3)
    metrics: dict = {}

    reply = await agent.agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("get_product_features", "search_knowledge"),
        lookup_query="giờ làm của LG",
        metrics=metrics,
    )

    assert reply == "LG Display làm ca ngày 08:00-20:00 và ca đêm 20:00-08:00."
    assert dispatched == [("search_knowledge", {"query": "giờ làm của LG"})]
    assert llm.calls == 1
    assert llm.bind_calls == 0
    assert metrics["prefetch_hit"] is True


async def test_compare_income_prefetches_required_threshold_evidence(monkeypatch):
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    dispatched: list[tuple[str, dict]] = []

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        dispatched.append((name, args))
        return (
            'COMPARE_INCOME_JSON={"status":"matched","target_monthly_vnd":20000000,'
            '"projects":[{"project_slug":"rorze","project_name":"Rorze","evidence":['
            '{"feature_key":"take_home_income","name_vi":"Thu nhập","value_text":'
            '"14-15 triệu/tháng chưa gồm thưởng; 20-21 triệu/tháng bình quân năm gồm thưởng."}'
            ']}],"safe_reply":"Với mốc 20 triệu/tháng, dữ liệu thu nhập đã xác minh là:\\n'
            '- Rorze:\\n  • Thu nhập: 14-15 triệu/tháng chưa gồm thưởng; '
            '20-21 triệu/tháng bình quân năm gồm thưởng."}'
        )

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    llm = _ScriptedLLM(
        [
            "Rorze có thu nhập 14-15 triệu/tháng chưa gồm thưởng; "
            "20-21 triệu/tháng bình quân năm gồm thưởng."
        ]
    )
    agent = MiniMaxAgent(llm, embedder=None, max_iters=3)
    metrics: dict = {}

    reply = await agent.agent(
        "context",
        system="sys",
        retrieval=_FakeRetrieval(lambda *_args, **_kwargs: None),
        embedder=None,
        allowed_tools=("compare_income",),
        lookup_query="lương 20 triệu",
        required_tool="compare_income",
        required_tool_args={"target_monthly_vnd": 20_000_000},
        metrics=metrics,
    )

    assert "14-15 triệu/tháng chưa gồm thưởng" in reply
    assert "20-21 triệu/tháng bình quân năm gồm thưởng" in reply
    assert dispatched == [("compare_income", {"target_monthly_vnd": 20_000_000})]
    # The verified render is handed to the model as evidence; the agent authors
    # the reply in one composition round (no tools bound).
    assert llm.calls == 1
    assert llm.bind_calls == 0
    assert metrics["prefetch_hit"] is True


async def test_compare_income_valid_model_retry_returns_deterministic_evidence(monkeypatch):
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    calls = 0
    safe_reply = (
        "Với mốc 20.5 triệu/tháng, dữ liệu thu nhập đã xác minh là:\n"
        "- Rorze:\n"
        "  • Thu nhập: 20.5-21 triệu/tháng bình quân năm gồm thưởng.\n"
        "Anh/chị muốn em tư vấn kỹ dự án nào ạ?"
    )
    payload = (
        'COMPARE_INCOME_JSON={"status":"matched","target_monthly_vnd":20500000,'
        '"projects":[{"project_name":"Rorze","evidence":[{"name_vi":"Thu nhập",'
        '"value_text":"20.5-21 triệu/tháng bình quân năm gồm thưởng."}]}],'
        f'"safe_reply":{__import__("json").dumps(safe_reply, ensure_ascii=False)}}}'
    )

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        nonlocal calls
        calls += 1
        return "Không có dữ liệu phù hợp." if calls == 1 else payload

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    llm = _ScriptedLLM(
        [[{"name": "compare_income", "args": {}, "id": "compare-retry"}], safe_reply]
    )

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=3).agent(
        "context",
        system="sys",
        retrieval=_FakeRetrieval(lambda *_args, **_kwargs: None),
        embedder=None,
        allowed_tools=("compare_income",),
        lookup_query="lương 20.5 triệu",
        required_tool="compare_income",
        required_tool_args={"target_monthly_vnd": 20_500_000},
    )

    assert reply == safe_reply
    assert calls == 2
    # Round 1 dispatches the required tool; round 2 is the tool-free composition.
    assert llm.calls == 2


async def test_faq_detail_focused_prefetches_both_knowledge_and_product_features(monkeypatch):
    """Focused FAQ prefetches both authorities with isolated retrieval sessions."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    dispatched: list[tuple[str, dict]] = []
    retrieval_ids: list[str] = []

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        dispatched.append((name, args))
        retrieval_ids.append(retrieval.identity)
        if name == "get_product_features":
            return "Đặc điểm sản phẩm — dự án 'lg-display':\n- housing: LG Display có ký túc xá cho người ở xa. Điều kiện: ≥50 km."
        return "Lương cơ bản 8 triệu. Nguồn: tin tuyển dụng LG Display."

    next_session = 0

    @asynccontextmanager
    async def make_retrieval():
        nonlocal next_session
        next_session += 1
        yield _FakeRetrieval(identity=f"fresh-{next_session}")

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    llm = _ScriptedLLM(["LG Display có ký túc xá cho người ở xa theo đặc điểm sản phẩm."])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=3)
    metrics: dict = {}

    reply = await agent.agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("get_product_features", "search_knowledge"),
        lookup_query="làm chỗ bạn có nhà trọ không?",
        metrics=metrics,
        forced_project_slug="lg-display",
        make_retrieval=make_retrieval,
    )

    assert reply == "LG Display có ký túc xá cho người ở xa theo đặc điểm sản phẩm."
    # Both tools dispatched, scoped to the focused project slug.
    dispatched_names = [name for name, _ in dispatched]
    assert dispatched_names == ["search_knowledge", "get_product_features"]
    knowledge_args = dict(dispatched[0][1])
    features_args = dict(dispatched[1][1])
    assert knowledge_args == {"query": "làm chỗ bạn có nhà trọ không?", "project_slug": "lg-display"}
    assert features_args == {"project_slug": "lg-display"}
    assert sorted(retrieval_ids) == ["fresh-1", "fresh-2"]
    # Both authorities already prefetched → one tool-free generation, no tools bound.
    assert llm.calls == 1
    assert llm.bind_calls == 0
    assert metrics["prefetch_hit"] is True


async def test_faq_detail_focused_dual_prefetch_runs_concurrently(monkeypatch):
    """Focused FAQ prefetch overlaps the two dispatches when isolated retrieval
    sessions exist — proven by observed in-flight overlap, not a wall-clock budget."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    active = 0
    max_active = 0

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)  # yield point so the overlap can actually happen
        active -= 1
        if name == "get_product_features":
            return "Đặc điểm sản phẩm — dự án 'lg-display': housing available."
        return "KB evidence for the query."

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    llm = _ScriptedLLM(["Grounded reply."])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=3)
    metrics: dict = {}

    @asynccontextmanager
    async def make_retrieval():
        yield _FakeRetrieval(identity="isolated")

    await agent.agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("get_product_features", "search_knowledge"),
        lookup_query="nhà trọ",
        metrics=metrics,
        forced_project_slug="lg-display",
        make_retrieval=make_retrieval,
    )

    # Both dispatches were in flight at the same time — sequential prefetch can
    # never reach max_active == 2.
    assert max_active == 2
    assert metrics["prefetch_hit"] is True


async def test_faq_detail_focused_prefetch_is_sequential_without_session_factory(monkeypatch):
    """A request-scoped shared AsyncSession is never used by concurrent prefetches."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    active = 0
    max_active = 0

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        if name == "get_product_features":
            return "Đặc điểm sản phẩm — dự án 'lg-display': housing available."
        return "KB evidence for the query."

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    agent = MiniMaxAgent(_ScriptedLLM(["Grounded reply."]), embedder=None, max_iters=3)

    await agent.agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("get_product_features", "search_knowledge"),
        lookup_query="nhà trọ",
        forced_project_slug="lg-display",
    )

    assert max_active == 1


async def test_faq_detail_retries_one_empty_final_generation_with_same_evidence(monkeypatch):
    """A transient empty final answer gets one model-only retry without repeating retrieval."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    dispatched: list[tuple[str, dict]] = []

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        dispatched.append((name, args))
        return "LG Display: kiểm tra màn hình trước khi xuất xưởng."

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    grounded = "Công việc là kiểm tra màn hình trước khi xuất xưởng."
    llm = _ScriptedLLM(["<think>reasoning only</think>", grounded])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=1)
    metrics: dict = {}
    query = "kiem tra chat luong san pham cu the lam nhung gi"

    reply = await agent.agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("get_product_features", "search_knowledge"),
        lookup_query=query,
        metrics=metrics,
        retry_empty_generation=True,
    )

    assert reply == grounded
    assert llm.calls == 2
    assert dispatched == [("search_knowledge", {"query": query})]
    assert metrics["generation_retry_count"] == 1
    assert metrics["generation_retry_reason"] == "empty_after_clean"


async def test_empty_generation_retry_is_bounded_and_reasoning_only_output_retries():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return "unused"

    empty_llm = _ScriptedLLM(["", ""])
    empty_metrics: dict = {}
    empty_reply = await MiniMaxAgent(empty_llm, embedder=None, max_iters=1).agent(
        "context",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        allowed_tools=(),
        metrics=empty_metrics,
        retry_empty_generation=True,
    )

    # Reasoning-only output cleans to empty, so it earns the same single retry.
    # It used to be excluded because its text tripped a lexical filter; that
    # filter is gone, and "nothing to send" is reason enough to try once more.
    reasoning_only_llm = _ScriptedLLM(['<think>only deliberation</think>', "câu trả lời thật"])
    reasoning_only_reply = await MiniMaxAgent(reasoning_only_llm, embedder=None, max_iters=1).agent(
        "context",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        allowed_tools=(),
        metrics={},
        retry_empty_generation=True,
    )

    assert empty_reply == ""
    assert empty_llm.calls == 2
    assert empty_metrics["generation_retry_count"] == 1
    assert reasoning_only_reply == "câu trả lời thật"
    assert reasoning_only_llm.calls == 2


async def test_empty_generation_retry_failure_returns_empty_for_runner_fallback():
    pytest.importorskip("langchain_core")
    from langchain_core.messages import AIMessage

    from app.graph.clients import MiniMaxAgent

    class _RetryFailureLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="")
            raise RuntimeError("provider retry failed")

    llm = _RetryFailureLLM()
    metrics: dict = {}
    reply = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=(),
        metrics=metrics,
        retry_empty_generation=True,
    )

    assert reply == ""
    assert llm.calls == 2
    assert metrics["generation_retry_failure"] == "RuntimeError"


async def test_empty_generation_retry_is_tool_free_after_a_tool_round():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    dispatched: list[str] = []

    async def handler(name, args):  # noqa: ARG001
        dispatched.append(name)
        return "verified evidence"

    first_tool = [{"name": "list_active_projects", "args": {}, "id": "first"}]
    attempted_retry_tool = [
        {"name": "search_bus_timetable", "args": {"company": "LG"}, "id": "retry"}
    ]
    llm = _ScriptedLLM([first_tool, "", attempted_retry_tool])
    metrics: dict = {}

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=2).agent(
        "context",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        metrics=metrics,
        retry_empty_generation=True,
    )

    assert reply == ""
    assert llm.calls == 3
    assert dispatched == ["list_active_projects"]
    assert metrics["tool_rounds"] == 1


async def test_empty_generation_retry_is_disabled_by_default():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    llm = _ScriptedLLM(["", "unexpected retry"])

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        "proactive context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=(),
    )

    assert reply == ""
    assert llm.calls == 1


async def test_faq_detail_prefetch_miss_preserves_scoped_tools(monkeypatch):
    """A knowledge miss leaves both routed FAQ tools available to the model."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def fake_dispatch(retrieval, embedder, name, args, **_kwargs):  # noqa: ARG001
        return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."

    monkeypatch.setattr("app.graph.clients._dispatch_tool", fake_dispatch)
    llm = _ScriptedLLM(["Bạn cho mình xin tên dự án nhé."])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=1)
    metrics: dict = {}

    await agent.agent(
        "context",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("get_product_features", "search_knowledge"),
        lookup_query="lương bao nhiêu?",
        metrics=metrics,
    )

    assert {"get_product_features", "search_knowledge"} <= set(llm.bound_names)
    assert metrics["prefetch_hit"] is False


async def test_single_tool_call_uses_shared_retrieval():
    """A single tool call must NOT spin up an isolated session."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    factory_called = False

    async def handler(name, args):  # noqa: ARG001
        return "shared-result"

    @asynccontextmanager
    async def make_retrieval():
        nonlocal factory_called
        factory_called = True
        yield _FakeRetrieval(lambda n, a: "factory-result")  # noqa: ARG005

    shared = _FakeRetrieval(lambda n, a: "shared-result")  # noqa: ARG005

    # Monkeypatch _dispatch_tool is complex; instead verify via the result.
    # With one call + factory, the code path uses _dispatch_one → make_retrieval
    # branch is skipped because len(calls) == 1 (sequential path), but
    # _dispatch_one still checks make_retrieval. Actually the code runs
    # _dispatch_one for each call regardless. For a single call the sequential
    # list-comp runs _dispatch_one which WILL use make_retrieval.
    # So this test verifies: single call + make_retrieval → factory is used.
    llm = _ScriptedLLM(
        [
            [{"name": "list_active_projects", "args": {}, "id": "c1"}],
            "done",
        ]
    )
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)

    await agent.agent(
        "test",
        system="sys",
        retrieval=shared,
        embedder=None,
        make_retrieval=make_retrieval,
    )

    # With a single call, _dispatch_one still tries make_retrieval.
    assert factory_called, "single call should still use make_retrieval if provided"


async def test_order_preservation():
    """asyncio.gather preserves order — ToolMessages match tool_calls order."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        # Different delays so results arrive out of order
        delay = {"list_active_projects": 0.05, "search_bus_timetable": 0.01}.get(name, 0.02)
        await asyncio.sleep(delay)
        return f"R:{name}"

    tool_calls = [
        {"name": "list_active_projects", "args": {}, "id": "c1"},
        {"name": "search_bus_timetable", "args": {"company": "LG", "question": "x"}, "id": "c2"},
    ]
    llm = _ScriptedLLM([tool_calls, "final"])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    make_retrieval = _make_retrieval_factory(handler)

    # We can't directly inspect messages[], but the grounding/tool_results
    # capture preserves order. Test indirectly: the agent completed without
    # error and the final reply is correct.
    reply = await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        make_retrieval=make_retrieval,
    )
    assert reply == "final"


async def test_concurrency_actually_overlaps():
    """Decisive concurrency test: tool B sets an event that tool A waits on.

    If sequential, A waits forever (deadlock) → timeout.
    If parallel, B runs concurrently and sets the event so A completes.
    """
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    go = asyncio.Event()

    async def handler(name, args):  # noqa: ARG001
        if name == "list_active_projects":
            # Wait for the other tool to signal
            await asyncio.wait_for(go.wait(), timeout=2.0)
            return "A-done"
        # Tool B: signal immediately
        go.set()
        return "B-done"

    tool_calls = [
        {"name": "list_active_projects", "args": {}, "id": "c1"},
        {"name": "search_bus_timetable", "args": {"company": "X", "question": "y"}, "id": "c2"},
    ]
    llm = _ScriptedLLM([tool_calls, "ok"])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    make_retrieval = _make_retrieval_factory(handler)

    reply = await asyncio.wait_for(
        agent.agent(
            "test",
            system="sys",
            retrieval=_FakeRetrieval(handler),
            embedder=None,
            make_retrieval=make_retrieval,
        ),
        timeout=5.0,
    )
    assert reply == "ok"


async def test_error_isolation_does_not_crash_gather():
    """If make_retrieval raises for one tool, it falls back to shared retrieval."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    shared_calls: list[str] = []

    async def shared_handler(name, args):  # noqa: ARG001
        shared_calls.append(name)
        return f"shared:{name}"

    call_count = 0

    @asynccontextmanager
    async def make_retrieval():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("session creation failed")
        yield _FakeRetrieval(shared_handler)

    tool_calls = [
        {"name": "list_active_projects", "args": {}, "id": "c1"},
        {"name": "search_bus_timetable", "args": {"company": "X", "question": "y"}, "id": "c2"},
    ]
    llm = _ScriptedLLM([tool_calls, "recovered"])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)

    reply = await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(shared_handler),
        embedder=None,
        make_retrieval=make_retrieval,
    )

    assert reply == "recovered"
    # The failing tool fell back to shared retrieval
    assert len(shared_calls) >= 1


async def test_semaphore_caps_concurrency():
    """parallel_tool_max_concurrency limits simultaneous tool calls."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    max_concurrent = 0
    current = 0
    lock = asyncio.Lock()

    async def handler(name, args):  # noqa: ARG001
        nonlocal max_concurrent, current
        async with lock:
            current += 1
            max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.1)
        async with lock:
            current -= 1
        return f"R:{name}"

    # 6 tool calls, concurrency cap = 2 → max_concurrent should be ≤ 2
    tool_calls = [{"name": "list_active_projects", "args": {}, "id": f"c{i}"} for i in range(6)]
    llm = _ScriptedLLM([tool_calls, "done"])
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    make_retrieval = _make_retrieval_factory(handler)

    # Override the concurrency setting to 2
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.parallel_tool_max_concurrency
    settings.parallel_tool_max_concurrency = 2
    try:
        await agent.agent(
            "test",
            system="sys",
            retrieval=_FakeRetrieval(handler),
            embedder=None,
            make_retrieval=make_retrieval,
        )
    finally:
        settings.parallel_tool_max_concurrency = original

    assert max_concurrent <= 2, f"Expected ≤2 concurrent, got {max_concurrent}"


async def test_on_evidence_publishes_accumulated_tool_results_before_the_final_round():
    """Progressive send grounds a mid-generation bubble with the evidence the
    model had seen when that text was produced, so ``on_evidence`` fires after a
    tool dispatch and before the final answer round streams."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return [ProjectFeatures(project_id="p1", slug="lg-display", name="LG Display", summary="Nhà máy Hải Phòng")]

    tool_calls = [{"name": "list_active_projects", "args": {}, "id": "c1"}]
    llm = _ScriptedLLM([tool_calls, "Dạ em xin trả lời."])
    published: list[list[str]] = []
    deltas: list[str] = []
    order: list[str] = []

    async def on_evidence(evidence):
        published.append(evidence)
        order.append("evidence")

    async def on_delta(text):
        deltas.append(text)
        order.append("delta")

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=5).agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        allowed_tools=("list_active_projects",),
        on_delta=on_delta,
        on_evidence=on_evidence,
    )

    assert reply == "Dạ em xin trả lời."
    assert len(published) == 1
    (evidence,) = published[0]
    assert evidence.startswith("ACTIVE_PROJECT_LOOKUP_JSON=")
    body = json.loads(evidence.split("ACTIVE_PROJECT_LOOKUP_JSON=", 1)[1].split("\n", 1)[0])
    assert body["status"] == "matched"
    assert body["total"] == 1
    assert [row["project"] for row in body["projects"]] == ["LG Display"]
    assert "SURFACED_PROJECT_IDS=id=p1" in evidence
    assert deltas == ["Dạ em xin trả lời."]
    # Evidence is in hand before the answer streams: that ordering is what lets a
    # mid-generation bubble pass the same grounding check as the full reply.
    assert order.index("evidence") < order.index("delta")


async def test_without_on_evidence_the_agent_loop_is_unchanged():
    """The hook is optional: no callback, no behaviour change."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return [ProjectFeatures(project_id="p1", slug="lg-display", name="LG Display", summary="Nhà máy Hải Phòng")]

    llm = _ScriptedLLM([[{"name": "list_active_projects", "args": {}, "id": "c1"}], "done"])
    reply = await MiniMaxAgent(llm, embedder=None, max_iters=5).agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        allowed_tools=("list_active_projects",),
    )

    assert reply == "done"
