"""Tests for Phase 5 model tiering — route strategy → fast-model eligibility.

The runner decides whether a turn qualifies for the fast-tier model via
``should_use_fast_model``. The agent then switches LLMs only when a fast model
is actually configured. These tests pin the eligibility policy + the agent's
switch behavior; the LLM construction is covered by the existing factories tests.
"""

from __future__ import annotations

from app.graph.router import (
    FAST_MODEL_STRATEGIES,
    route_turn,
    should_use_fast_model,
)


# --- should_use_fast_model (eligibility policy) ------------------------------


def test_small_talk_is_eligible_for_fast_model():
    assert should_use_fast_model(route_turn("cảm ơn bạn nhiều"))


def test_contact_lookup_is_eligible_for_fast_model():
    assert should_use_fast_model(route_turn("liên hệ admin số mấy?"))


def test_out_of_scope_safe_redirect_is_eligible_for_fast_model():
    assert should_use_fast_model(route_turn("viết code giúp tôi"))


def test_recommendation_uses_reasoning_model():
    """Recommendation needs the reasoning model — not fast-tier."""
    assert not should_use_fast_model(route_turn("gợi ý việc phù hợp"))


def test_profile_update_uses_reasoning_model():
    assert not should_use_fast_model(route_turn("tôi tên là Lan"))


def test_timetable_uses_reasoning_model():
    """Timetable needs structured tool reasoning — not fast-tier."""
    assert not should_use_fast_model(route_turn("xe đưa đón ca đêm mấy giờ?"))


def test_general_fallback_uses_reasoning_model():
    assert not should_use_fast_model(route_turn("hôm nay thế nào"))


def test_fast_model_strategies_are_a_frozen_set():
    """The eligibility set is immutable — prevents accidental mutation."""
    assert isinstance(FAST_MODEL_STRATEGIES, frozenset)


# --- MiniMaxAgent switch behavior -------------------------------------------


async def test_agent_uses_fast_llm_when_use_fast_and_configured():
    """When use_fast=True and a fast_llm exists, the agent must bind the fast model."""
    pytest = __import__("pytest")
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    class _RecordingLLM:
        def __init__(self, name: str) -> None:
            self.name = name

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages, **kwargs):
            import types

            return types.SimpleNamespace(content=f"reply:{self.name}", tool_calls=None)

    fast = _RecordingLLM("fast")
    primary = _RecordingLLM("primary")
    agent = MiniMaxAgent(primary, embedder=None, max_iters=1, fast_llm=fast)

    reply = await agent.agent(
        "thanks", system="sys", retrieval=object(), embedder=None, use_fast=True
    )
    assert "fast" in reply


async def test_agent_uses_primary_llm_when_use_fast_but_no_fast_configured():
    """use_fast=True with no fast_llm → falls back to primary (unconfigured deployment)."""
    pytest = __import__("pytest")
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    class _RecordingLLM:
        def __init__(self, name: str) -> None:
            self.name = name

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages, **kwargs):
            import types

            return types.SimpleNamespace(content=f"reply:{self.name}", tool_calls=None)

    primary = _RecordingLLM("primary")
    agent = MiniMaxAgent(primary, embedder=None, max_iters=1, fast_llm=None)

    reply = await agent.agent(
        "thanks", system="sys", retrieval=object(), embedder=None, use_fast=True
    )
    assert "primary" in reply


async def test_agent_uses_primary_llm_when_use_fast_false():
    """use_fast=False always uses the primary, even when fast is configured."""
    pytest = __import__("pytest")
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    class _RecordingLLM:
        def __init__(self, name: str) -> None:
            self.name = name

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages, **kwargs):
            import types

            return types.SimpleNamespace(content=f"reply:{self.name}", tool_calls=None)

    fast = _RecordingLLM("fast")
    primary = _RecordingLLM("primary")
    agent = MiniMaxAgent(primary, embedder=None, max_iters=1, fast_llm=fast)

    reply = await agent.agent(
        "gợi ý việc", system="sys", retrieval=object(), embedder=None, use_fast=False
    )
    assert "primary" in reply
