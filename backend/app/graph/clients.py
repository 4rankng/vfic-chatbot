"""LLM/embedder clients + MiniMax/OpenRouter agent/safety/digest factories.

Heavy SDKs (google-genai, langchain-openai / langchain-core) are imported LAZILY inside
methods so importing this module stays cheap and free of optional-dependency failures at
import time. Tool schemas + dispatch live in ``schemas.py``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
from typing import Literal

from app.core.config import get_settings
from app.graph.schemas import _dispatch_tool
from app.graph.usage import record_token_usage as _record_token_usage

logger = logging.getLogger(__name__)

# ── LLM observability helpers (Redis-backed, process-agnostic) ──────────────
_RKEY_429 = "llm:minimax_429s"  # INCR on 429, EXPIRE 60 (rolling minute)
_RKEY_INVOKE_COUNT = "llm:invoke_count"
_RKEY_INVOKE_MS = "llm:invoke_total_ms"
_RKEY_FALLBACK_COUNT = "llm:fallback_count"


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


def _record_llm_fallback() -> None:
    """Increment primary->fallback LLM failover count (best-effort, non-fatal)."""
    try:
        from app.core.redis import get_redis_sync

        r = get_redis_sync()
        r.incr(_RKEY_FALLBACK_COUNT)
        r.expire(_RKEY_FALLBACK_COUNT, 120)
    except Exception:  # noqa: BLE001
        logger.warning("failed to record llm fallback to redis", exc_info=True)


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


def _ground_reply(reply: str, tool_results: list[str]) -> str:
    """Post-generation grounding cross-check (Phase 3).

    Strips any job_id the reply cites that was not present in the tool results
    the LLM was shown. Best-effort and never raises — on any error the original
    reply passes through unchanged (grounding is a guardrail, not a hard gate).
    """
    try:
        from app.core.config import get_settings

        if not getattr(get_settings(), "grounding_check_enabled", True):
            return reply
        from app.graph.grounding import extract_surfaced_job_ids, validate_grounding

        surfaced = extract_surfaced_job_ids(tool_results)
        result = validate_grounding(reply, surfaced)
        if not result.is_grounded:
            logger.warning(
                "grounding_hallucination_stripped: %s cited ids not in retrieved set",
                len(result.hallucinated_ids),
            )
            return result.sanitized_reply
        return reply
    except Exception:  # noqa: BLE001
        logger.debug("grounding check skipped (non-fatal)", exc_info=True)
        return reply


async def _llm_call_with_retry(bound, messages):
    """Call bound.ainvoke with 1 retry on 429 (settings.llm_429_retry_sleep_seconds backoff).

    On second 429, raises LLMThrottled so the worker can send a static
    degradation message without making another LLM call.
    """
    from app.core.config import get_settings
    from app.graph.llm_semaphore import LLMThrottled

    try:
        return await bound.ainvoke(messages)
    except Exception as exc:
        if _is_429(exc):
            _record_llm_429()
            logger.warning("llm_429_retry", exc_info=True)
            await asyncio.sleep(get_settings().llm_429_retry_sleep_seconds)
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

    async def __call__(self, text: str) -> list[float]:
        return await self.embed(text)

    async def batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in chunked SDK calls.

        Gemini's per-request token budget is shared across the batch.  Sending
        all texts at once silently truncates, returning fewer vectors than
        texts.  This method chunks into sub-batches to stay within limits
        and guarantee one vector per input.
        """
        if not texts:
            return []
        if not self.s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings")
        from app.graph.llm_semaphore import get_embed_semaphore
        from google import genai

        embed_sem = get_embed_semaphore()
        if self._client is None:
            self._client = genai.Client(api_key=self.s.gemini_api_key)
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self._EMBED_BATCH_SIZE):
            chunk = texts[i : i + self._EMBED_BATCH_SIZE]
            async with embed_sem:
                resp = await self._client.aio.models.embed_content(
                    model=self.s.gemini_embedding_model,
                    contents=chunk,
                )
            if resp.embeddings:
                all_vectors.extend(list(e.values) for e in resp.embeddings)
            else:
                # API returned no embeddings — pad with zero vectors so the
                # caller (embed_with_fallback) can retry one-by-one.
                all_vectors.extend([0.0] * (self.s.embedding_dim or 768) for _ in chunk)
        return all_vectors


class OpenRouterEmbedder:
    """OpenRouter embeddings client using the OpenAI-compatible embeddings API."""

    _EMBED_BATCH_SIZE = 96

    def __init__(
        self,
        settings=None,
        *,
        api_key: str | None = None,
    ) -> None:
        self.s = settings or get_settings()
        self.api_key = api_key or self.s.openrouter_api_key

    async def embed(self, text: str) -> list[float]:
        return (await self.batch([text]))[0]

    async def __call__(self, text: str) -> list[float]:
        return await self.embed(text)

    async def batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter embeddings")

        import httpx

        url = f"{self.s.openrouter_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self._EMBED_BATCH_SIZE):
            chunk = texts[i : i + self._EMBED_BATCH_SIZE]
            payload = {
                "model": self.s.openrouter_embedding_model,
                "input": chunk,
                "dimensions": self.s.embedding_dim,
            }
            async with httpx.AsyncClient(timeout=self.s.openrouter_embedding_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
            rows = sorted(body.get("data", []), key=lambda row: row.get("index", 0))
            if len(rows) != len(chunk):
                raise RuntimeError(
                    f"OpenRouter embeddings returned {len(rows)} vectors for {len(chunk)} inputs"
                )
            vectors = [row.get("embedding") for row in rows]
            if not all(isinstance(vector, list) and vector for vector in vectors):
                raise RuntimeError("OpenRouter embeddings response did not include vectors")
            all_vectors.extend([[float(value) for value in vector] for vector in vectors])
        return all_vectors


def build_embedder(
    settings=None,
    *,
    openrouter_api_key: str | None = None,
):
    """Build the configured embedding client."""
    s = settings or get_settings()
    provider = (s.embedding_provider or "openrouter").strip().lower()
    if provider == "openrouter":
        return OpenRouterEmbedder(s, api_key=openrouter_api_key)
    if provider == "gemini":
        return GeminiEmbedder(s)
    raise RuntimeError("EMBEDDING_PROVIDER must be 'openrouter' or 'gemini'")


class MiniMaxAgent:
    """Tool-calling agent: loops on MiniMax tool_calls until a final text reply.

    ``fast_llm`` (optional, Phase 5 model tiering): when provided and the caller
    passes ``use_fast=True``, the lightweight model is used instead of the primary
    reasoning model. The runner decides eligibility via ``should_use_fast_model``.
    """

    def __init__(self, llm, embedder, max_iters: int | None = None, fast_llm=None) -> None:
        self.llm = llm
        self.embedder = embedder
        self.fast_llm = fast_llm
        # max_iters reads from settings unless explicitly overridden (tests, etc.).
        if max_iters is not None:
            self.max_iters = max_iters
        else:
            s = get_settings()
            self.max_iters = s.max_llm_calls_per_turn

    async def agent(self, user_text, *, system, retrieval, embedder, allowed_tools=None, use_fast=False) -> str:
        from app.graph.llm_semaphore import LLMThrottled, get_llm_semaphore
        from app.graph.schemas import filter_tool_schemas

        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        active_llm = self.fast_llm if (use_fast and self.fast_llm is not None) else self.llm
        schemas = filter_tool_schemas(allowed_tools)
        bound = active_llm.bind_tools(schemas) if hasattr(active_llm, "bind_tools") else active_llm
        sem = get_llm_semaphore()
        messages = [SystemMessage(content=system)]
        tool_results: list[str] = []  # captured for post-generation grounding cross-check
        if _should_prefetch_knowledge(user_text):
            try:
                prefetched = await _dispatch_tool(
                    retrieval,
                    embedder,
                    "search_knowledge",
                    {"query": user_text},
                )
            except Exception:  # noqa: BLE001
                logger.warning("Contact knowledge prefetch failed", exc_info=True)
            else:
                tool_results.append(str(prefetched))
                messages.append(
                    SystemMessage(
                        content=(
                            "KẾT QUẢ TRA CỨU KB CHỦ ĐỘNG CHO CÂU HỎI LIÊN HỆ/ADMIN/SỐ ĐIỆN THOẠI:\n"
                            f"{prefetched}\n\n"
                            "Nếu kết quả có liên hệ hoặc số điện thoại từ KB, "
                            "hãy trả lời trực tiếp theo dữ liệu đó. "
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
            # Phase 6: capture token usage + cost from the response.usage block.
            _record_token_usage(getattr(ai, "usage_metadata", None) or getattr(ai, "response_metadata", {}).get("token_usage"))
            logger.info("llm_invoke", extra={"llm_latency_ms": elapsed_ms})
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None)
            if not calls:
                return _ground_reply(ai.content, tool_results)
            # MiniMax occasionally omits tool_call.id; an empty tool_call_id breaks
            # the OpenAI tool protocol on the next turn. Synthesize a stable id.
            for idx, tc in enumerate(calls):
                out = await _dispatch_tool(retrieval, embedder, tc["name"], tc.get("args", {}))
                tool_results.append(str(out))
                messages.append(
                    ToolMessage(
                        content=str(out),
                        tool_call_id=tc.get("id") or f"call_{idx}_{tc.get('name', 'tool')}",
                    )
                )
        final = messages[-1].content if hasattr(messages[-1], "content") else ""
        return _ground_reply(final, tool_results)


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
            self.primary.bind_tools(tools) if hasattr(self.primary, "bind_tools") else self.primary
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
            _record_llm_fallback()
            logger.warning("Primary LLM failed, falling back to secondary provider", exc_info=True)
            return await self.fallback.ainvoke(messages, **kwargs)


def _minimax_chat(
    model: str,
    *,
    temperature: float,
    max_retries: int = 0,
    api_key: str | None = None,
):
    """OpenAI-compatible MiniMax client from settings. Shared construction so
    model / base_url / timeout cannot drift between build_deps and the extractor.

    ``max_retries`` defaults to 0 because ``FallbackLLM`` already handles provider-
    level retry; the openai library's built-in retry would just waste time (3× the
    timeout) before the fallback kicks in.
    """
    s = get_settings()
    resolved_api_key = api_key or s.minimax_api_key
    if not resolved_api_key:
        raise RuntimeError("MINIMAX_API_KEY is required for MiniMax chat")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=resolved_api_key,
        base_url=s.minimax_base_url,
        timeout=s.minimax_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
    )


def _openrouter_chat(
    model: str,
    *,
    temperature: float,
    timeout: int | None = None,
    json_mode: bool = False,
    max_retries: int = 0,
    api_key: str | None = None,
):
    """OpenAI-compatible OpenRouter client from settings."""
    s = get_settings()
    resolved_api_key = api_key or s.openrouter_api_key
    if not resolved_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter chat")
    from langchain_openai import ChatOpenAI

    kwargs = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    return ChatOpenAI(
        model=model,
        api_key=resolved_api_key,
        base_url=s.openrouter_base_url,
        timeout=timeout or s.openrouter_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        **kwargs,
    )


def _active_llm_provider(settings=None) -> Literal["minimax", "openrouter"]:
    """Return the configured primary LLM provider name."""
    s = settings or get_settings()
    minimax_enabled = getattr(s, "minimax_enable", True)
    openrouter_enabled = getattr(s, "openrouter_enable", False)
    default_provider = getattr(s, "llm_default_provider", "minimax")
    if default_provider == "openrouter" and openrouter_enabled:
        return "openrouter"
    if default_provider == "minimax" and minimax_enabled:
        return "minimax"
    if openrouter_enabled:
        return "openrouter"
    if minimax_enabled:
        return "minimax"
    raise RuntimeError("No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true")


def _chat_for_role(
    role: ModelRole,
    *,
    temperature: float,
    json_mode: bool = False,
    minimax_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    minimax_enabled: bool | None = None,
    openrouter_enabled: bool | None = None,
    default_provider: Literal["minimax", "openrouter"] | None = None,
    openrouter_agent_model: str | None = None,
    openrouter_safety_model: str | None = None,
    openrouter_digest_model: str | None = None,
):
    """Build the OpenAI-compatible chat client for an agent/safety/digest role.

    When both providers are enabled, returns a ``FallbackLLM`` that tries the
    configured default first and automatically retries with the other provider.
    """
    s = get_settings()
    minimax_on = getattr(s, "minimax_enable", True) if minimax_enabled is None else minimax_enabled
    openrouter_on = (
        getattr(s, "openrouter_enable", False)
        if openrouter_enabled is None
        else openrouter_enabled
    )
    preferred = default_provider or getattr(s, "llm_default_provider", "minimax")

    if not minimax_on and not openrouter_on:
        raise RuntimeError(
            "No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true"
        )

    minimax_chat = None
    if minimax_on:
        resolved_minimax_key = minimax_api_key or s.minimax_api_key
        if role == "digest":
            if not resolved_minimax_key:
                raise RuntimeError("MINIMAX_API_KEY is required for MiniMax JSON generation")
            from langchain_openai import ChatOpenAI

            kwargs = (
                {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
            )
            minimax_chat = ChatOpenAI(
                model=s.minimax_digest_model or s.minimax_agent_model,
                api_key=resolved_minimax_key,
                base_url=s.minimax_base_url,
                timeout=s.minimax_digest_timeout,
                temperature=temperature,
                **kwargs,
            )
        else:
            model = s.minimax_agent_model if role == "agent" else s.minimax_safety_model
            minimax_chat = _minimax_chat(
                model,
                temperature=temperature,
                api_key=resolved_minimax_key,
            )

    openrouter_chat = None
    if openrouter_on:
        resolved_openrouter_key = openrouter_api_key or s.openrouter_api_key
        model = {
            "agent": openrouter_agent_model or s.openrouter_agent_model,
            "safety": openrouter_safety_model or s.openrouter_safety_model,
            "digest": (
                openrouter_digest_model
                or s.openrouter_digest_model
                or openrouter_agent_model
                or s.openrouter_agent_model
            ),
        }[role]
        timeout = s.openrouter_digest_timeout if role == "digest" else s.openrouter_request_timeout
        openrouter_chat = _openrouter_chat(
            model,
            temperature=temperature,
            timeout=timeout,
            json_mode=json_mode,
            api_key=resolved_openrouter_key,
        )

    if minimax_chat and openrouter_chat:
        if preferred == "openrouter":
            return FallbackLLM(openrouter_chat, minimax_chat)
        return FallbackLLM(minimax_chat, openrouter_chat)
    if minimax_chat:
        return minimax_chat
    return openrouter_chat
