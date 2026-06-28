"""Phase 4 characterization tests for the graph factories (GraphDeps wiring).

``_minimax_chat`` is stubbed so no real MiniMax key / network is needed — the test
verifies that ``build_deps`` still composes a fully-wired ``GraphDeps`` after the move
out of llm_real.py into factories.py.
"""
import pytest

from app.graph.clients import FallbackLLM, GeminiEmbedder, MiniMaxAgent, MiniMaxSafety
from app.graph.factories import build_deps, make_minimax_llm_json
from app.graph.types import GraphDeps


class _Settings:
    minimax_enable = True
    minimax_api_key = ""
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    minimax_digest_model = ""
    minimax_request_timeout = 60
    minimax_digest_timeout = 180
    openrouter_enable = False


class _SettingsWithFallback(_Settings):
    minimax_api_key = "sk-mm-fake"
    openrouter_enable = True
    openrouter_api_key = "sk-or-fake"
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v3.2"
    openrouter_safety_model = "deepseek/deepseek-v3.2"
    openrouter_digest_model = "deepseek/deepseek-v3.2"
    openrouter_request_timeout = 60
    openrouter_digest_timeout = 180


@pytest.mark.asyncio
async def test_build_deps_wires_graphdeps(monkeypatch):
    class _FakeLLM:
        pass

    monkeypatch.setattr("app.graph.factories._chat_for_role", lambda *a, **k: _FakeLLM())

    deps = await build_deps(object())
    assert isinstance(deps, GraphDeps)
    assert isinstance(deps.agent, MiniMaxAgent)
    assert isinstance(deps.safety, MiniMaxSafety)
    assert isinstance(deps.embedder, GeminiEmbedder)
    assert deps.zalo is not None


def test_minimax_json_missing_key_names_minimax(monkeypatch):
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        make_minimax_llm_json()


@pytest.mark.asyncio
async def test_fallback_llm_retries_on_primary_failure():
    """FallbackLLM tries primary first, falls back to secondary on exception."""

    class _FailLLM:
        async def ainvoke(self, messages, **kwargs):
            raise ConnectionError("primary down")

    class _OkLLM:
        async def ainvoke(self, messages, **kwargs):
            return "fallback-reply"

    wrapped = FallbackLLM(_FailLLM(), _OkLLM())
    result = await wrapped.ainvoke([])
    assert result == "fallback-reply"


@pytest.mark.asyncio
async def test_fallback_llm_primary_success_skips_fallback():
    """FallbackLLM returns primary result when it succeeds."""

    class _OkLLM:
        call_count = 0

        async def ainvoke(self, messages, **kwargs):
            self.call_count += 1
            return f"primary-{self.call_count}"

    class _ShouldNotBeCalled:
        async def ainvoke(self, messages, **kwargs):
            raise AssertionError("fallback should not be called when primary succeeds")

    wrapped = FallbackLLM(_OkLLM(), _ShouldNotBeCalled())
    result = await wrapped.ainvoke([])
    assert result == "primary-1"


@pytest.mark.asyncio
async def test_fallback_llm_bind_tools_returns_fallback_wrapped():
    """bind_tools on FallbackLLM returns a new FallbackLLM wrapping bound inner clients."""

    class _Bindable:
        def __init__(self, name):
            self.name = name
            self.bound = False

        def bind_tools(self, tools):
            self.bound = True
            return self

        async def ainvoke(self, messages, **kwargs):
            raise RuntimeError(f"{self.name} not mocked for ainvoke")

    primary = _Bindable("primary")
    fallback = _Bindable("fallback")
    wrapped = FallbackLLM(primary, fallback)
    bound = wrapped.bind_tools([{"type": "function", "function": {"name": "test"}}])
    assert isinstance(bound, FallbackLLM)
    assert primary.bound
    assert fallback.bound


def test_active_provider_no_xor_when_both_enabled(monkeypatch):
    """_active_llm_provider returns 'minimax' (primary) when both are enabled — no RuntimeError."""
    from app.graph.clients import _active_llm_provider

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithFallback())
    assert _active_llm_provider() == "minimax"


def test_active_provider_openrouter_only(monkeypatch):
    """_active_llm_provider returns 'openrouter' when only OpenRouter is enabled."""
    from app.graph.clients import _active_llm_provider

    s = _SettingsWithFallback()
    s.minimax_enable = False
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: s)
    assert _active_llm_provider() == "openrouter"


def test_chat_for_role_returns_fallback_when_both_enabled(monkeypatch):
    """_chat_for_role returns a FallbackLLM wrapping both providers when both are enabled."""
    from app.graph.clients import _chat_for_role

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithFallback())
    llm = _chat_for_role("agent", temperature=0.3)
    assert isinstance(llm, FallbackLLM)
