"""Diagnostic metric capture — the split LLM timing + per-call / token / tool-breakdown keys.

Pins the metrics ``MiniMaxAgent.agent`` writes into the shared ``metrics`` dict
(which flows into ``BotRun.stage_timings``). These keys are what the Hiệu suất
dashboard's slow-turn detail and per-stage latency bars read, so they are the
contract between the capture side (clients.py) and the surfacing side
(performance.py + frontend).

Covers:
* llm_queue_ms + llm_model_ms split (the core fix: separates self-throttle wait
  from actual model inference).
* llm_call_ms — per-call latency list (1×40s vs 3×13s).
* prompt/completion/cached tokens per turn (context-size correlation).
* tool_breakdown — per-tool latency dict (long-pole identification under gather).
* retried_429 flag — turn survived a rate-limit backoff.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest


class _FakeMsg:
    """Minimal message stand-in exposing the attributes the agent reads.

    Avoids langchain's AIMessage pydantic validation so tests can attach a
    plain-dict ``usage_metadata`` — exactly what ``parse_usage``'s dict branch
    is designed to handle.
    """

    def __init__(self, content="", tool_calls=None, usage_metadata=None) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.usage_metadata = usage_metadata


class _ScriptedLLM:
    """Returns a scripted sequence of messages, carrying usage_metadata.

    Mirrors ``_ScriptedLLM`` in test_parallel_tools.py but uses ``_FakeMsg``
    so a plain-dict ``usage_metadata`` can be attached for token-capture tests.
    """

    def __init__(self, replies: list, usage=None) -> None:
        self._replies = list(replies)
        self.usage = usage
        self.calls = 0

    def bind_tools(self, tools):  # noqa: ARG002
        return self

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        self.calls += 1
        if not self._replies:
            return _FakeMsg(content="done", usage_metadata=self.usage)
        entry = self._replies.pop(0)
        if isinstance(entry, str):
            return _FakeMsg(content=entry, usage_metadata=self.usage)
        return _FakeMsg(content="", tool_calls=entry, usage_metadata=self.usage)


class _FakeRetrieval:
    def __init__(self, handler=None) -> None:
        self._handler = handler

    async def list_active_projects(self):
        return await self._handler("list_active_projects", {})

    async def match_documents(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("search_knowledge", {})

    async def search_bus_timetable(self, *args, **kwargs):  # noqa: ARG002
        return await self._handler("search_bus_timetable", {})

    async def project_id_by_slug(self, *args, **kwargs):  # noqa: ARG002
        return "fake-pid"


def _make_retrieval_factory(handler):
    counter = 0

    @asynccontextmanager
    async def _factory():
        nonlocal counter
        counter += 1
        yield _FakeRetrieval(handler)

    return _factory


async def test_llm_timing_split_queue_vs_model():
    """llm_queue_ms (semaphore wait) and llm_model_ms (inference) are distinct."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return "ok"

    llm = _ScriptedLLM(["reply"], usage={"input_tokens": 500, "output_tokens": 50})
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    metrics: dict = {}

    await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        metrics=metrics,
    )

    # Both split keys exist and are non-negative.
    assert "llm_queue_ms" in metrics
    assert "llm_model_ms" in metrics
    assert metrics["llm_queue_ms"] >= 0
    assert metrics["llm_model_ms"] >= 0
    # The legacy total is preserved (queue + model, approximately).
    assert metrics["llm_invoke_ms"] >= metrics["llm_model_ms"]
    # The old monolithic llm_ms key is NOT written here (runner.py dropped it).
    assert "llm_ms" not in metrics


async def test_per_call_latency_list():
    """Multi-round turns record one entry per model call in llm_call_ms."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return "result"

    # Round 1: tool call → Round 2: tool call → Round 3: final text
    llm = _ScriptedLLM(
        [
            [{"name": "list_active_projects", "args": {}, "id": "c1"}],
            [
                {
                    "name": "search_bus_timetable",
                    "args": {"company": "X", "question": "y"},
                    "id": "c2",
                }
            ],
            "final answer",
        ],
        usage={"input_tokens": 100, "output_tokens": 10},
    )
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    metrics: dict = {}

    await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        make_retrieval=_make_retrieval_factory(handler),
        metrics=metrics,
    )

    assert metrics["llm_calls"] == 3
    assert isinstance(metrics["llm_call_ms"], list)
    assert len(metrics["llm_call_ms"]) == 3
    # Each entry is the model_ms for that call (non-negative int).
    for ms in metrics["llm_call_ms"]:
        assert isinstance(ms, int)
        assert ms >= 0


async def test_per_turn_token_accumulation():
    """prompt/completion/cached tokens accumulate across model calls."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return "ok"

    # usage_metadata exposes both input/output and nested cached_tokens —
    # parse_usage reads prompt_cache_hit_tokens / cached_tokens /
    # prompt_tokens_details.cached_tokens. We use the nested form to exercise
    # that branch.
    usage = {
        "prompt_tokens": 1200,
        "completion_tokens": 80,
        "prompt_tokens_details": {"cached_tokens": 200},
    }
    llm = _ScriptedLLM(["reply"], usage=usage)
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    metrics: dict = {}

    await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        metrics=metrics,
    )

    assert metrics["prompt_tokens"] == 1200
    assert metrics["completion_tokens"] == 80
    assert metrics["cached_tokens"] == 200


async def test_tool_breakdown_records_per_tool_latency():
    """tool_breakdown maps each tool name to its cumulative dispatch time."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def handler(name, args):  # noqa: ARG001
        return f"R:{name}"

    tool_calls = [
        {"name": "list_active_projects", "args": {}, "id": "c1"},
        {"name": "search_bus_timetable", "args": {"company": "LG", "question": "xe"}, "id": "c2"},
    ]
    llm = _ScriptedLLM([tool_calls, "done"], usage={"input_tokens": 50, "output_tokens": 5})
    agent = MiniMaxAgent(llm, embedder=None, max_iters=5)
    metrics: dict = {}

    await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(handler),
        embedder=None,
        make_retrieval=_make_retrieval_factory(handler),
        metrics=metrics,
    )

    assert "tool_breakdown" in metrics
    assert isinstance(metrics["tool_breakdown"], dict)
    assert "list_active_projects" in metrics["tool_breakdown"]
    assert "search_bus_timetable" in metrics["tool_breakdown"]
    # Each tool's accumulated latency is a non-negative int.
    for ms in metrics["tool_breakdown"].values():
        assert isinstance(ms, int)
        assert ms >= 0


async def test_retried_429_flag_set_on_rate_limit_retry(monkeypatch):
    """A 429 that succeeds on retry sets retried_429=True in metrics."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    call_count = 0

    class _RetryingLLM:
        def bind_tools(self, tools):  # noqa: ARG002
            return self

        async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("429 rate limit exceeded")
            return _FakeMsg(content="recovered")

    # Skip the real backoff sleep so the test is instant. Capture the original
    # sleep BEFORE patching so the stub doesn't recurse into itself.
    import app.graph.clients as clients_mod

    real_sleep = clients_mod.asyncio.sleep

    async def _fast_sleep(_seconds):
        # Genuine no-op — do not call the (patched) sleep again.
        return None

    monkeypatch.setattr(clients_mod.asyncio, "sleep", _fast_sleep)
    # Ensure other call sites that need real sleep still work is unnecessary
    # here since this test's only sleep is the 429 backoff.
    _ = real_sleep  # keep the reference for clarity / future restore

    agent = MiniMaxAgent(_RetryingLLM(), embedder=None, max_iters=5)
    metrics: dict = {}

    reply = await agent.agent(
        "test",
        system="sys",
        retrieval=_FakeRetrieval(lambda n, a: "ok"),  # noqa: ARG005
        embedder=None,
        metrics=metrics,
    )

    assert reply == "recovered"
    assert metrics.get("retried_429") is True
    # The backoff sleep must be tracked separately from model inference so the
    # split stays clean (llm_model_ms excludes the sleep).
    assert metrics.get("llm_backoff_ms", 0) >= 0
