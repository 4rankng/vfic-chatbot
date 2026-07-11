"""Tests for graph factories and GraphDeps wiring."""

import pytest

from app.graph.clients import MiniMaxAgent, MiniMaxSafety, OpenRouterEmbedder
from app.graph.factories import build_deps, make_minimax_llm_json
from app.graph.types import GraphDeps


class _Settings:
    minimax_enable = True
    llm_default_provider = "minimax"
    minimax_api_key = ""
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    minimax_digest_model = ""
    minimax_request_timeout = 60
    minimax_digest_timeout = 180
    openrouter_enable = False
    embedding_provider = "openrouter"
    embedding_dim = 3072
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_api_key = ""
    openrouter_embedding_model = "openai/text-embedding-3-large"
    openrouter_embedding_timeout = 60


class _SettingsWithFallback(_Settings):
    """Both providers enabled (legacy name kept; no runtime fallback anymore)."""

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
    assert isinstance(deps.embedder, OpenRouterEmbedder)
    assert deps.zalo is not None


def test_minimax_json_missing_key_names_minimax(monkeypatch):
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        make_minimax_llm_json()


def test_active_provider_no_xor_when_both_enabled(monkeypatch):
    """_active_llm_provider returns the configured default when both are enabled."""
    from app.graph.clients import _active_llm_provider

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithFallback())
    assert _active_llm_provider() == "minimax"


def test_active_provider_openrouter_default_when_both_enabled(monkeypatch):
    """_active_llm_provider can use OpenRouter as primary when both are enabled."""
    from app.graph.clients import _active_llm_provider

    class _OpenRouterDefault(_SettingsWithFallback):
        llm_default_provider = "openrouter"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouterDefault())
    assert _active_llm_provider() == "openrouter"


def test_active_provider_openrouter_only(monkeypatch):
    """_active_llm_provider returns 'openrouter' when only OpenRouter is enabled."""
    from app.graph.clients import _active_llm_provider

    s = _SettingsWithFallback()
    s.minimax_enable = False
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: s)
    assert _active_llm_provider() == "openrouter"


def test_chat_for_role_returns_plain_client_default_minimax(monkeypatch):
    """_chat_for_role returns a plain ChatOpenAI for the default provider (no wrapper)."""
    from langchain_openai import ChatOpenAI

    from app.graph.clients import _chat_for_role

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithFallback())
    llm = _chat_for_role("agent", temperature=0.3)
    # No FallbackLLM wrapper — a plain ChatOpenAI for the single active provider.
    assert isinstance(llm, ChatOpenAI)


def test_chat_for_role_returns_openrouter_client_when_default(monkeypatch):
    """_chat_for_role honors LLM_DEFAULT_PROVIDER=openrouter at the client level."""
    from langchain_openai import ChatOpenAI

    from app.graph.clients import _chat_for_role

    class _OpenRouterDefault(_SettingsWithFallback):
        llm_default_provider = "openrouter"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouterDefault())
    llm = _chat_for_role("agent", temperature=0.3)
    assert isinstance(llm, ChatOpenAI)
    # The model name reflects the openrouter config, proving provider selection.
    assert "deepseek" in llm.model_name
