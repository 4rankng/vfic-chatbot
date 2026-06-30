"""Tests for graph clients + tool schemas/dispatch."""
import pytest

from app.graph.clients import GeminiEmbedder, _active_llm_provider, _chat_for_role, _minimax_chat
from app.graph.schemas import TOOL_SCHEMAS, _dispatch_tool


class _Settings:
    gemini_api_key = ""
    gemini_embedding_model = "gemini-embedding-2"
    minimax_enable = True
    minimax_api_key = ""
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_request_timeout = 60
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    minimax_digest_model = ""
    minimax_digest_timeout = 180
    openrouter_enable = False
    openrouter_api_key = ""
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v3.2"
    openrouter_safety_model = "deepseek/deepseek-v3.2"
    openrouter_digest_model = "deepseek/deepseek-v3.2"
    openrouter_request_timeout = 60
    openrouter_digest_timeout = 180

# Tool names _dispatch_tool knows how to route.
_DISPATCHED = {
    "search_user_memory",
    "search_knowledge",
    "list_active_projects",
    "search_bus_timetable",
    "get_product_features",
}


@pytest.mark.asyncio
async def test_dispatch_tool_unknown_name_returns_marker():
    assert await _dispatch_tool(None, None, "does_not_exist", {}) == "unknown tool"
    assert await _dispatch_tool(None, None, "", None) == "unknown tool"


def test_every_tool_schema_name_is_dispatchable():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names <= _DISPATCHED  # no schema describes a tool the dispatcher can't route
    assert "get_product_features" in names  # the newest tool is wired end-to-end


@pytest.mark.asyncio
async def test_gemini_embedder_empty_batch_returns_empty_without_sdk():
    # Empty-input early-returns [] before touching google.genai — no API key needed.
    assert await GeminiEmbedder().batch([]) == []


@pytest.mark.asyncio
async def test_gemini_embedder_missing_key_names_gemini():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await GeminiEmbedder(_Settings()).batch(["hello"])


def test_minimax_chat_missing_key_names_minimax(monkeypatch):
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        _minimax_chat("MiniMax-M2.7-highspeed", temperature=0.1)


def test_active_llm_provider_returns_minimax_when_both_enabled():
    """When both providers are enabled, minimax is primary (no XOR error)."""
    class _Both(_Settings):
        openrouter_enable = True

    assert _active_llm_provider(_Both()) == "minimax"


def test_openrouter_chat_missing_key_names_openrouter(monkeypatch):
    class _OpenRouter(_Settings):
        minimax_enable = False
        openrouter_enable = True

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouter())
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        _chat_for_role("agent", temperature=0.1)
