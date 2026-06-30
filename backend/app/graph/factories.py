"""Dependency factories for the graph's LLM/embedder wiring.

- ``build_deps`` wires the full ``GraphDeps`` for the chatbot worker.
- ``build_minimax_extractor`` — candidate extraction (persistence worker).
- ``make_minimax_llm_json`` — JSON-mode LLM for the knowledge training pipeline (ingest worker).

langchain_openai is imported lazily inside each factory so the web-process import path
stays langchain-free.
"""
from __future__ import annotations

import logging

from app.core.config import get_settings
from app.graph.clients import GeminiEmbedder, MiniMaxAgent, MiniMaxSafety, _chat_for_role
from app.graph.types import GraphDeps

logger = logging.getLogger(__name__)


def build_minimax_extractor():
    """MiniMax extractor (safety model, temp 0) for candidate extraction."""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _chat_for_role("safety", temperature=0.0)

    async def extractor(system: str, user: str) -> str:
        return (await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])).content

    return extractor


def make_minimax_llm_json():
    """(system, user) -> json_text callable for the LLM training pipeline.

    OpenAI-compatible MiniMax client with JSON-object response mode. Falls back to the
    agent model when MINIMAX_DIGEST_MODEL is unset. Imported lazily by the ingest worker
    only, so the app/tests never need langchain-openai at import time.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    llm = _chat_for_role("digest", temperature=0.1, json_mode=True)

    async def _call(system: str, user: str) -> str:
        return (await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])).content

    return _call


async def build_deps(db):
    """Wire the full GraphDeps for one chatbot turn (agent + safety + embedder + zalo)."""
    from app.services.zalo_bot_service import ZaloBotSender

    s = get_settings()
    agent_llm = _chat_for_role("agent", temperature=0.3)
    safety_llm = _chat_for_role("safety", temperature=0.0)
    embedder = GeminiEmbedder(s)
    return GraphDeps(
        db=db,
        agent=MiniMaxAgent(agent_llm, embedder),
        safety=MiniMaxSafety(safety_llm),
        embedder=embedder,
        zalo=ZaloBotSender(),
    )
