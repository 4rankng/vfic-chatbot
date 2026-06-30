"""LLM/embedder clients: GeminiEmbedder + MiniMax agent/safety + shared chat factory.

Heavy SDKs (google-genai, langchain-openai / langchain-core) are imported LAZILY inside
methods so importing this module stays cheap and free of optional-dependency failures at
import time. Tool schemas + dispatch live in ``schemas.py``.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import unicodedata
from typing import Literal

from app.core.config import get_settings
from app.graph.schemas import TOOL_SCHEMAS, _dispatch_tool

logger = logging.getLogger(__name__)

# ── LLM observability helpers (Redis-backed, process-agnostic) ──────────────
_RKEY_429 = "llm:minimax_429s"      # INCR on 429, EXPIRE 60 (rolling minute)
_RKEY_INVOKE_COUNT = "llm:invoke_count"
_RKEY_INVOKE_MS = "llm:invoke_total_ms"


def _record_llm_latency(ms: int) -> None:
    """Persist LLM call latency + count to Redis (best-effort, non-fatal)."""
    try:
        from app.core.redis import get_redis_sync

        r = get_redis_sync()
        pipe = r.pipeline()
        pipe.incr(_RKEY_INVOKE_COUNT)
        pipe.incrby(_RKEY_INVOKE_MS, ms)
        pipe.expire(_RKEY_INVOKE_COUNT, 120)
        pipe.expire(_RKEY_INVOKE_MS, 120)
        pipe.execute()
    except Exception:  # noqa: BLE001
        logger.warning("failed to record llm latency to redis", exc_info=True)


def _record_llm_429() -> None:
    """Increment MiniMax 429 counter in Redis (best-effort, non-fatal)."""
    try:
        from app.core.redis import get_redis_sync

        r = get_redis_sync()
        r.incr(_RKEY_429)
        r.expire(_RKEY_429, 60)  # rolling 1-minute window
    except Exception:  # noqa: BLE001
        logger.warning("failed to record llm 429 to redis", exc_info=True)
ModelRole = Literal["agent", "safety", "digest"]


def _normalize_query_hint(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.replace("đ", "d").replace("Đ", "D").lower()


def _should_prefetch_knowledge(user_text: str) -> bool:
    """Detect queries where skipping KB retrieval causes false "I don't know" replies.

    Contact/admin/phone questions should see KB facts before the model answers.
    """
    text = _normalize_query_hint(user_text)
    contact_terms = (
        "lien he",
        "admin",
        "so dien thoai",
        "sdt",
        "phone",
        "hotline",
        "zalo",
        "den cong ty",
    )
    return any(term in text for term in contact_terms)


def _is_429(exc: Exception) -> bool:
    """Check if an exception represents an HTTP 429 (rate limit)."""
    return "429" in str(exc) or "rate" in str(exc).lower()


async def _llm_call_with_retry(bound, messages):
    """Call bound.ainvoke with 1 retry on 429 (2s ± 0.5s jitter).

    On second 429, raises LLMThrottled so the worker can send a static
    degradation message without making another LLM call.
    """
    from app.graph.llm_semaphore import LLMThrottled

    try:
        return await bound.ainvoke(messages)
    except Exception as exc:
        if _is_429(exc):
            _record_llm_429()
            logger.warning("llm_429_retry", exc_info=True)
            await asyncio.sleep(2.0 + random.uniform(-0.5, 0.5))
            try:
                return await bound.ainvoke(messages)
            except Exception as exc2:
                if _is_429(exc2):
                    _record_llm_429()
                    raise LLMThrottled("LLM rate limit exhausted after retry")
                raise
        raise


class GeminiEmbedder:
    def __init__(self, settings=None) -> None:
        self.s = settings or get_settings()
        self._client = None

    # Gemini's per-request token budget is shared across all inputs; large
    # batches silently truncate, returning fewer vectors than texts.  Chunk
    # into sub-batches so each request stays within limits and returns
    # exactly one vector per input.
    _EMBED_BATCH_SIZE = 100

    async def embed(self, text: str) -> list[float]:
        return (await self.batch([text]))[0]

    async def batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in chunked SDK calls.

        Gemini's per-request token budget is shared across the batch.  Sending
        all texts at once silently truncates, returning fewer vectors than
        texts.  This method chunks into sub-batches to stay within limits
        and guarantee one vector per input.
        """
        from app.graph.llm_semaphore import get_embed_semaphore
        from google import genai

        embed_sem = get_embed_semaphore()
        if not texts:
            return []
        if not self.s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings")
        if self._client is None:
            self._client = genai.Client(api_key=self.s.gemini_api_key)
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self._EMBED_BATCH_SIZE):
            chunk = texts[i : i + self._EMBED_BATCH_SIZE]
            async with embed_sem:
                resp = await self._client.aio.models.embed_content(
                    model=self.s.gemini_embedding_model, contents=chunk,
                )
            if resp.embeddings:
                all_vectors.extend(list(e.values) for e in resp.embeddings)
            else:
                # API returned no embeddings — pad with zero vectors so the
                # caller (embed_with_fallback) can retry one-by-one.
                all_vectors.extend([0.0] * (self.s.embedding_dim or 768) for _ in chunk)
        return all_vectors


class MiniMaxAgent:
    """Tool-calling agent: loops on MiniMax tool_calls until a final text reply."""

    def __init__(self, llm, embedder, max_iters: int | None = None) -> None:
        self.llm = llm
        self.embedder = embedder
        # max_iters reads from settings unless explicitly overridden (tests, etc.).
        if max_iters is not None:
            self.max_iters = max_iters
        else:
            s = get_settings()
            self.max_iters = s.max_llm_calls_per_turn

    async def agent(self, user_text, *, system, db, embedder) -> str:
        from app.graph.llm_semaphore import LLMThrottled, get_llm_semaphore

        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        bound = self.llm.bind_tools(TOOL_SCHEMAS) if hasattr(self.llm, "bind_tools") else self.llm
        sem = get_llm_semaphore()
        messages = [SystemMessage(content=system)]
        if _should_prefetch_knowledge(user_text):
            try:
                prefetched = await _dispatch_tool(db, embedder, "search_knowledge", {"query": user_text})
            except Exception:  # noqa: BLE001
                logger.warning("Contact knowledge prefetch failed", exc_info=True)
            else:
                messages.append(
                    SystemMessage(
                        content=(
                            "KẾT QUẢ TRA CỨU KB CHỦ ĐỘNG CHO CÂU HỎI LIÊN HỆ/ADMIN/SỐ ĐIỆN THOẠI:\n"
                            f"{prefetched}\n\n"
                            "Nếu kết quả có liên hệ hoặc số điện thoại từ KB, hãy trả lời trực tiếp theo dữ liệu đó. "
                            "Nếu không có, mới nói chưa có thông tin trong dữ liệu."
                        )
                    )
                )
        messages.append(HumanMessage(content=user_text))
        for _ in range(self.max_iters):
            t0 = time.monotonic()
            try:
                async with sem:
                    ai = await _llm_call_with_retry(bound, messages)
            except LLMThrottled:
                raise
            except Exception as exc:
                # Track non-retry-path 429s for observability (Phase 0 metric).
                if _is_429(exc):
                    _record_llm_429()
                    logger.error("llm_429", exc_info=True)
                raise
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            _record_llm_latency(elapsed_ms)
            logger.info("llm_invoke", extra={"llm_latency_ms": elapsed_ms})
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


def _minimax_chat(model: str, *, temperature: float, max_retries: int = 0):
    """OpenAI-compatible MiniMax client from settings. Shared construction so
    model / base_url / timeout cannot drift between build_deps and the extractor.

    ``max_retries`` defaults to 0 because ``FallbackLLM`` already handles provider-
    level retry; the openai library's built-in retry would just waste time (3× the
    timeout) before the fallback kicks in.
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
        max_retries=max_retries,
    )


def _openrouter_chat(model: str, *, temperature: float, timeout: int | None = None, json_mode: bool = False, max_retries: int = 0):
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
        max_retries=max_retries,
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
