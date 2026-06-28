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


class FallbackLLM:
    """Wraps a primary and fallback ChatOpenAI. On primary failure, retries once with fallback.

    Transparent to callers: supports ``bind_tools`` and ``ainvoke`` just like ChatOpenAI,
    so the existing agent/safety/digest code works unchanged.
    """

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    def bind_tools(self, tools):
        bound_primary = (
            self.primary.bind_tools(tools)
            if hasattr(self.primary, "bind_tools")
            else self.primary
        )
        bound_fallback = (
            self.fallback.bind_tools(tools)
            if hasattr(self.fallback, "bind_tools")
            else self.fallback
        )
        return FallbackLLM(bound_primary, bound_fallback)

    async def ainvoke(self, messages, **kwargs):
        try:
            return await self.primary.ainvoke(messages, **kwargs)
        except Exception:
            logger.warning("Primary LLM failed, falling back to OpenRouter", exc_info=True)
            return await self.fallback.ainvoke(messages, **kwargs)


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
    """Return the *primary* LLM provider name. MiniMax is always primary when enabled."""
    s = settings or get_settings()
    minimax_enabled = getattr(s, "minimax_enable", True)
    openrouter_enabled = getattr(s, "openrouter_enable", False)
    if minimax_enabled:
        return "minimax"
    if openrouter_enabled:
        return "openrouter"
    raise RuntimeError("No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true")


def _chat_for_role(role: ModelRole, *, temperature: float, json_mode: bool = False):
    """Build the OpenAI-compatible chat client for an agent/safety/digest role.

    When both MINIMAX_ENABLE and OPENROUTER_ENABLE are true, returns a ``FallbackLLM``
    that tries MiniMax first and automatically retries with OpenRouter on failure.
    """
    from langchain_openai import ChatOpenAI

    s = get_settings()
    minimax_enabled = getattr(s, "minimax_enable", True)
    openrouter_enabled = getattr(s, "openrouter_enable", False)

    if not minimax_enabled and not openrouter_enabled:
        raise RuntimeError("No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true")

    # Build MiniMax client (primary when enabled)
    primary = None
    if minimax_enabled:
        if role == "digest":
            if not s.minimax_api_key:
                raise RuntimeError("MINIMAX_API_KEY is required for MiniMax JSON generation")
            kwargs = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
            primary = ChatOpenAI(
                model=s.minimax_digest_model or s.minimax_agent_model,
                api_key=s.minimax_api_key,
                base_url=s.minimax_base_url,
                timeout=s.minimax_digest_timeout,
                temperature=temperature,
                **kwargs,
            )
        else:
            model = s.minimax_agent_model if role == "agent" else s.minimax_safety_model
            primary = _minimax_chat(model, temperature=temperature)

    # Build OpenRouter client (fallback when MiniMax is also enabled, or sole provider)
    fallback = None
    if openrouter_enabled:
        model = {
            "agent": s.openrouter_agent_model,
            "safety": s.openrouter_safety_model,
            "digest": s.openrouter_digest_model or s.openrouter_agent_model,
        }[role]
        timeout = s.openrouter_digest_timeout if role == "digest" else s.openrouter_request_timeout
        fallback = _openrouter_chat(model, temperature=temperature, timeout=timeout, json_mode=json_mode)

    if primary and fallback:
        return FallbackLLM(primary, fallback)
    if primary:
        return primary
    return fallback
