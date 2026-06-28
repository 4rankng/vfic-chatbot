"""LLM/embedder clients: GeminiEmbedder + MiniMax agent/safety + shared chat factory.

Heavy SDKs (google-genai, langchain-openai / langchain-core) are imported LAZILY inside
methods so importing this module stays cheap and free of optional-dependency failures at
import time. Tool schemas + dispatch live in ``schemas.py``.
"""
from __future__ import annotations

import logging
from typing import Literal

from app.core.config import get_settings
from app.graph.schemas import TOOL_SCHEMAS, _dispatch_tool

logger = logging.getLogger(__name__)
ModelRole = Literal["agent", "safety", "digest"]


class GeminiEmbedder:
    def __init__(self, settings=None) -> None:
        self.s = settings or get_settings()
        self._client = None

    async def batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in ONE SDK call (Gemini accepts a `contents` list).

        Replaces the N+1 pattern of calling embed() per fact in MemoryService.save.
        """
        from google import genai

        if not texts:
            return []
        if not self.s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings")
        if self._client is None:
            self._client = genai.Client(api_key=self.s.gemini_api_key)
        resp = await self._client.aio.models.embed_content(
            model=self.s.gemini_embedding_model, contents=texts
        )
        return [list(e.values) for e in resp.embeddings]

    async def embed(self, text: str) -> list[float]:
        return (await self.batch([text]))[0]

    # The graph wires this object where the Embedder Callable[[str], ...] contract is
    # expected (tools.py does `await embedder(query)`), so the instance must be callable.
    __call__ = embed


class MiniMaxAgent:
    """Tool-calling agent: loops on MiniMax tool_calls until a final text reply."""

    def __init__(self, llm, embedder, max_iters: int = 4) -> None:
        self.llm = llm
        self.embedder = embedder
        self.max_iters = max_iters

    async def agent(self, user_text, *, system, db, embedder) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        bound = self.llm.bind_tools(TOOL_SCHEMAS) if hasattr(self.llm, "bind_tools") else self.llm
        messages = [SystemMessage(content=system), HumanMessage(content=user_text)]
        for _ in range(self.max_iters):
            ai = await bound.ainvoke(messages)
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None)
            if not calls:
                return ai.content
            # MiniMax occasionally omits tool_call.id; an empty tool_call_id breaks
            # the OpenAI tool protocol on the next turn. Synthesize a stable id.
            for idx, tc in enumerate(calls):
                out = await _dispatch_tool(db, embedder, tc["name"], tc.get("args", {}))
                messages.append(
                    ToolMessage(
                        content=str(out),
                        tool_call_id=tc.get("id") or f"call_{idx}_{tc.get('name', 'tool')}",
                    )
                )
        return messages[-1].content if hasattr(messages[-1], "content") else ""


class MiniMaxSafety:
    def __init__(self, llm) -> None:
        self.llm = llm

    async def safety(self, candidate_reply: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.graph.prompts import SAFETY_PROMPT

        resp = await self.llm.ainvoke(
            [SystemMessage(content=SAFETY_PROMPT), HumanMessage(content=candidate_reply)]
        )
        return resp.content


def _minimax_chat(model: str, *, temperature: float):
    """OpenAI-compatible MiniMax client from settings. Shared construction so
    model / base_url / timeout cannot drift between build_deps and the extractor.
    """
    from langchain_openai import ChatOpenAI

    s = get_settings()
    if not s.minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY is required for MiniMax chat")
    return ChatOpenAI(
        model=model,
        api_key=s.minimax_api_key,
        base_url=s.minimax_base_url,
        timeout=s.minimax_request_timeout,
        temperature=temperature,
    )


def _openrouter_chat(model: str, *, temperature: float, timeout: int | None = None, json_mode: bool = False):
    """OpenAI-compatible OpenRouter client from settings."""
    from langchain_openai import ChatOpenAI

    s = get_settings()
    if not s.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter chat")
    kwargs = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    return ChatOpenAI(
        model=model,
        api_key=s.openrouter_api_key,
        base_url=s.openrouter_base_url,
        timeout=timeout or s.openrouter_request_timeout,
        temperature=temperature,
        **kwargs,
    )


def _active_llm_provider(settings=None) -> Literal["minimax", "openrouter"]:
    s = settings or get_settings()
    minimax_enabled = getattr(s, "minimax_enable", True)
    openrouter_enabled = getattr(s, "openrouter_enable", False)
    if minimax_enabled and openrouter_enabled:
        raise RuntimeError("Enable only one LLM provider: set either MINIMAX_ENABLE or OPENROUTER_ENABLE")
    if openrouter_enabled:
        return "openrouter"
    if minimax_enabled:
        return "minimax"
    raise RuntimeError("No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true")


def _chat_for_role(role: ModelRole, *, temperature: float, json_mode: bool = False):
    """Build the selected OpenAI-compatible chat client for an agent/safety/digest role."""
    from langchain_openai import ChatOpenAI

    s = get_settings()
    provider = _active_llm_provider(s)
    if provider == "openrouter":
        model = {
            "agent": s.openrouter_agent_model,
            "safety": s.openrouter_safety_model,
            "digest": s.openrouter_digest_model or s.openrouter_agent_model,
        }[role]
        timeout = s.openrouter_digest_timeout if role == "digest" else s.openrouter_request_timeout
        return _openrouter_chat(model, temperature=temperature, timeout=timeout, json_mode=json_mode)

    if role == "digest":
        if not s.minimax_api_key:
            raise RuntimeError("MINIMAX_API_KEY is required for MiniMax JSON generation")
        kwargs = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
        return ChatOpenAI(
            model=s.minimax_digest_model or s.minimax_agent_model,
            api_key=s.minimax_api_key,
            base_url=s.minimax_base_url,
            timeout=s.minimax_digest_timeout,
            temperature=temperature,
            **kwargs,
        )
    model = s.minimax_agent_model if role == "agent" else s.minimax_safety_model
    return _minimax_chat(model, temperature=temperature)
