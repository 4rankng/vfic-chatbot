"""Two guards on ``MiniMaxAgent.agent``'s tool loop.

1. Every model round takes the deployment-wide Redis LLM semaphore. The parallel
   tool dispatcher used to bind its own in-process semaphore to the SAME local
   name, so the first multi-tool round silently moved every later round of that
   turn out of the cap (and out of the LLMThrottled fail-fast).
2. A turn that spends its whole budget on tool calls returns the lane's neutral
   "unavailable" line. The exhaustion path used to fall back to
   ``messages[-1].content``, which after a tool round is the raw ToolMessage
   payload — and ``ground_reply`` waves tool text through precisely because the
   ids inside it are in the surfaced set by construction.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest

from app.recruitment.domain.recommendation import ProjectFeatures

# The assertions observe acquisition ORDER, not wall-clock budgets; this only
# guards against an event-loop hang.
pytestmark = pytest.mark.timeout(30)


class _ScriptedLLM:
    """Returns a scripted sequence of responses, then a final no-tool reply."""

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.calls = 0
        self.model_name = "scripted-model"
        self.trace_provider = "minimax"

    def bind_tools(self, tools, **_kwargs):  # noqa: ARG002
        return self

    async def ainvoke(self, messages, **_kwargs):
        from langchain_core.messages import AIMessage

        self.calls += 1
        if not self._replies:
            return AIMessage(content="done")
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
    """A GraphRetrievalPort stand-in whose signatures match the real tool calls.

    ``_dispatch_tool`` forwards each tool its own argument shape (e.g.
    ``search_bus_timetable(retrieval, company, question, strict_company=...)``),
    and ``list_active_projects`` takes no arguments and returns
    ``ProjectFeatures`` rows — so the handler's return value has to be the
    right shape per tool, not a string.
    """

    def __init__(self, handler, identity: str = "shared") -> None:
        self._handler = handler
        self.identity = identity

    async def list_active_projects(self):
        return await self._handler("list_active_projects", {})

    async def match_documents(self, *_args, **_kwargs):
        return await self._handler("search_knowledge", {})

    async def match_faq(self, *_args, **_kwargs):
        return await self._handler("match_faq", {})

    async def match_memories(self, *_args, **_kwargs):
        return await self._handler("search_user_memory", {})

    async def active_projects_with_card(self, *_args, **_kwargs):
        return await self._handler("active_projects_with_card", {})

    async def search_bus_timetable(self, *_args, **_kwargs):
        return await self._handler("search_bus_timetable", {})

    async def job_features_for_project(self, *_args, **_kwargs):
        return await self._handler("get_product_features", {})

    async def income_summary_for_active_projects(self, *_args, **_kwargs):
        return await self._handler("compare_income", {})

    async def project_id_by_slug(self, *_args, **_kwargs):
        return "fake-pid"


def _make_retrieval_factory(handler, identity_prefix: str = "isolated"):
    counter = 0

    @asynccontextmanager
    async def _factory():
        nonlocal counter
        counter += 1
        yield _FakeRetrieval(handler, identity=f"{identity_prefix}-{counter}")

    return _factory


class _RecordingLLMSemaphore:
    """Stands in for the Redis semaphore and records acquisition order."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def __aenter__(self):
        self._events.append("llm_acquire")
        return self

    async def __aexit__(self, *_exc):
        self._events.append("llm_release")
        return False


async def test_post_tool_round_reacquires_the_deployment_llm_cap(monkeypatch):
    """A round AFTER a parallel tool round still takes the Redis semaphore.

    Ordering is the assertion, not a counter alone: the second acquisition must
    land after both tool dispatches. A local name rebound to the tool semaphore
    would make the post-tool round acquire an ``asyncio.Semaphore`` instead, so
    only one acquisition would ever be recorded.
    """
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    events: list[str] = []
    monkeypatch.setattr(
        "app.graph.llm_semaphore.get_llm_semaphore",
        lambda: _RecordingLLMSemaphore(events),
    )

    async def handler(name, _args):
        events.append(f"tool:{name}")
        if name == "list_active_projects":
            return [ProjectFeatures(project_id="p1", slug="lg-display", name="LG Display")]
        return f"result-{name}"

    tool_calls = [
        {"name": "list_active_projects", "args": {}, "id": "c1"},
        {"name": "search_bus_timetable", "args": {"company": "LG"}, "id": "c2"},
    ]
    llm = _ScriptedLLM([tool_calls, "all done"])

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=5).agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        make_retrieval=_make_retrieval_factory(handler),
    )

    assert reply == "all done"
    # One acquisition per model round — the first (tool request) and the second
    # (the answer round that follows the dispatch).
    assert events.count("llm_acquire") == 2
    last_acquire = len(events) - 1 - events[::-1].index("llm_acquire")
    assert last_acquire > events.index("tool:list_active_projects")
    assert last_acquire > events.index("tool:search_bus_timetable")


async def test_tool_loop_exhaustion_composes_instead_of_shipping_the_tool_payload(monkeypatch):
    """A turn with no text round gets one tool-free composition round, not a canned line.

    The tool result below is a payload the grounding cross-check cannot reject
    (its ids are in the surfaced set by construction), so the only thing standing
    between the candidate and that raw text is the exhaustion branch itself.
    """
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent
    from app.graph.tools.catalog import list_active_projects

    async def handler(_name, _args):
        return [ProjectFeatures(project_id="project-7", slug="du-an-7", name="Dự án 7")]

    # Two tool rounds exhaust the budget; the third scripted entry is the
    # tool-free composition round the exhaustion path now runs.
    llm = _ScriptedLLM(
        [[{"name": "list_active_projects", "args": {}, "id": "c"}]] * 2
        + ["Dạ hiện em chưa tra được thông tin, anh/chị thử lại sau nhé."]
    )
    metrics: dict[str, object] = {}

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=2).agent(
        "bên mình còn tuyển không?",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        metrics=metrics,
    )

    assert reply == "Dạ hiện em chưa tra được thông tin, anh/chị thử lại sau nhé."
    tool_output = await list_active_projects(_FakeRetrieval(handler))
    assert tool_output not in reply
    assert metrics["tool_loop_exhausted"] is True


async def test_tool_loop_exhaustion_suppresses_when_the_composition_round_is_empty(monkeypatch):
    """A tool-free composition round that produces nothing suppresses the turn."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(_name, _args):
        return [ProjectFeatures(project_id="project-7", slug="du-an-7", name="Dự án 7")]

    # Every round is a tool request: the composition round has nothing to say.
    llm = _ScriptedLLM([[{"name": "list_active_projects", "args": {}, "id": "c"}]] * 3)
    metrics: dict[str, object] = {}

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=2).agent(
        "bên mình còn tuyển không?",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        metrics=metrics,
    )

    assert reply == ""
    assert metrics["tool_loop_exhausted"] is True


async def test_vacancy_tool_loop_exhaustion_never_ships_the_raw_payload():
    """``list_active_projects`` exhaustion composes too; the raw payload never ships."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent
    from app.graph.tools.catalog import list_active_projects

    async def handler(_name, _args):
        return [ProjectFeatures(project_id="project-7", slug="du-an-7", name="Dự án 7")]

    llm = _ScriptedLLM(
        [[{"name": "list_active_projects", "args": {}, "id": "c"}]] * 2
        + ["Dạ em chưa kiểm tra được danh sách việc làm, anh/chị thử lại sau ạ."]
    )

    reply = await MiniMaxAgent(llm, embedder=None, max_iters=2).agent(
        "công ty nào đang tuyển?",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
    )

    tool_output = await list_active_projects(_FakeRetrieval(handler))
    assert reply == "Dạ em chưa kiểm tra được danh sách việc làm, anh/chị thử lại sau ạ."
    assert tool_output not in reply
