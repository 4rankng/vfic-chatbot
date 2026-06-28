"""Phase 4 characterization tests for the graph factories (GraphDeps wiring).

``_minimax_chat`` is stubbed so no real MiniMax key / network is needed — the test
verifies that ``build_deps`` still composes a fully-wired ``GraphDeps`` after the move
out of llm_real.py into factories.py.
"""
import pytest

from app.graph.clients import GeminiEmbedder, MiniMaxAgent, MiniMaxSafety
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
