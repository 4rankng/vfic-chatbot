"""Phase 4 characterization tests for the graph factories (GraphDeps wiring).

``_minimax_chat`` is stubbed so no real MiniMax key / network is needed — the test
verifies that ``build_deps`` still composes a fully-wired ``GraphDeps`` after the move
out of llm_real.py into factories.py.
"""
import pytest

from app.graph.clients import GeminiEmbedder, MiniMaxAgent, MiniMaxSafety
from app.graph.factories import build_deps
from app.graph.types import GraphDeps


@pytest.mark.asyncio
async def test_build_deps_wires_graphdeps(monkeypatch):
    class _FakeLLM:
        pass

    monkeypatch.setattr("app.graph.factories._minimax_chat", lambda *a, **k: _FakeLLM())

    deps = await build_deps(object())
    assert isinstance(deps, GraphDeps)
    assert isinstance(deps.agent, MiniMaxAgent)
    assert isinstance(deps.safety, MiniMaxSafety)
    assert isinstance(deps.embedder, GeminiEmbedder)
    assert deps.zalo is not None
