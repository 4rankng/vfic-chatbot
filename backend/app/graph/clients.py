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


def _usable_retrieval_prefetch(result: object) -> bool:
    """Whether a routed retrieval result is authoritative enough to inject."""
    text = str(result or "").strip()
    if not text:
        return False
    return not text.startswith(("Không tìm thấy", "Lỗi khi gọi tool", "unknown tool"))


async def _prefetch_tool(
    retrieval,
    embedder,
    name: str,
    args: dict,
    metrics: dict | None,
    resolved_registry: frozenset[str] | None = None,
) -> tuple[object, bool]:
    """Run one routed lookup with shared timing and fail-open semantics."""
    started = time.monotonic()
    if metrics is not None:
        metrics["prefetch_calls"] = metrics.get("prefetch_calls", 0) + 1
    try:
        result = await _dispatch_tool(
            retrieval,
            embedder,
            name,
            args,
            metrics=metrics,
            resolved_registry=resolved_registry,
        )
    except Exception:  # noqa: BLE001 — caller retains the normal tool loop
        logger.warning("%s prefetch failed", name, exc_info=True)
        result = ""
    finally:
        if metrics is not None:
            metrics["prefetch_ms"] = metrics.get("prefetch_ms", 0) + int(
                (time.monotonic() - started) * 1000
            )
    hit = _usable_retrieval_prefetch(result)
    if metrics is not None:
        metrics["prefetch_hit"] = hit
    return result, hit


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


async def _llm_call_with_retry(bound, messages, *, metrics: dict | None = None):
    """Call bound.ainvoke with 1 retry on 429 (settings.llm_429_retry_sleep_seconds backoff).

    On second 429, raises LLMThrottled so the worker can send a static
    degradation message without making another LLM call. When ``metrics`` is
    provided, sets ``retried_429 = True`` on the retry path so the dashboard can
    flag turns that survived a rate-limit backoff.

    Returns ``(result, backoff_ms)`` where ``backoff_ms`` is the wall-clock time
    spent sleeping during a rate-limit backoff (0 on the happy path). The caller
    uses this to exclude the sleep from ``llm_model_ms`` so the split stays
    clean — model inference never includes the 429 backoff.
    """
    from app.core.config import get_settings
    from app.graph.llm_semaphore import LLMThrottled

    try:
        return await bound.ainvoke(messages), 0
    except Exception as exc:
        if _is_429(exc):
            _record_llm_429()
            logger.warning("llm_429_retry", exc_info=True)
            backoff_t0 = time.monotonic()
            await asyncio.sleep(get_settings().llm_429_retry_sleep_seconds)
            backoff_ms = int((time.monotonic() - backoff_t0) * 1000)
            if metrics is not None:
                metrics["retried_429"] = True
            try:
                return await bound.ainvoke(messages), backoff_ms
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
            # Reuse the process-scoped OpenRouter embedding client (Tech-Lead
            # Directive §4) — embedding calls are the highest-volume HTTP path
            # in retrieval, and per-call TLS handshakes were a measurable tax
            # on every RAG turn. Auth (Bearer) is passed per-request.
            from app.core.http import get_http_client

            client = await get_http_client(
                "openrouter_embed",
                timeout=self.s.openrouter_embedding_timeout,
                settings=self.s,
            )
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

    async def agent(
        self,
        user_text,
        *,
        system,
        retrieval,
        embedder,
        allowed_tools=None,
        resolved_tool_registry: frozenset[str] | None = None,
        use_fast=False,
        make_retrieval=None,
        lookup_query: str | None = None,
        metrics: dict | None = None,
    ) -> str:
        from app.graph.llm_semaphore import LLMThrottled, get_llm_semaphore
        from app.graph.schemas import filter_tool_schemas

        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        active_llm = self.fast_llm if (use_fast and self.fast_llm is not None) else self.llm
        schemas = filter_tool_schemas(allowed_tools, resolved_registry=resolved_tool_registry)
        sem = get_llm_semaphore()
        messages = [SystemMessage(content=system)]
        tool_results: list[str] = []  # captured for post-generation grounding cross-check
        if metrics is not None:
            for key in (
                "llm_calls",
                "llm_invoke_ms",
                "llm_queue_ms",
                "llm_model_ms",
                "llm_backoff_ms",
                "prompt_tokens",
                "completion_tokens",
                "cached_tokens",
                "tool_calls",
                "tool_rounds",
                "tool_ms",
                "prefetch_calls",
                "prefetch_ms",
                "rag_cache_lookup_ms",
            ):
                metrics.setdefault(key, 0)
            metrics.setdefault("llm_call_ms", [])
        effective_query = lookup_query or user_text
        timetable_route = allowed_tools == ("search_bus_timetable",)
        faq_detail_route = allowed_tools == (
            "get_product_features",
            "search_knowledge",
        )
        if (
            _should_prefetch_knowledge(effective_query)
            and not timetable_route
            and not faq_detail_route
        ):
            try:
                prefetched = await _dispatch_tool(
                    retrieval,
                    embedder,
                    "search_knowledge",
                    {"query": effective_query},
                    metrics=metrics,
                    resolved_registry=resolved_tool_registry,
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
        if timetable_route:
            prefetched, prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "search_bus_timetable",
                {"company": "", "question": effective_query},
                metrics,
                resolved_tool_registry,
            )
            if prefetch_hit:
                tool_results.append(str(prefetched))
                messages.append(
                    SystemMessage(
                        content=(
                            "KẾT QUẢ TRA CỨU LỊCH XE ĐÃ THỰC HIỆN CHO TIN NHẮN NÀY:\n"
                            f"{prefetched}\n\n"
                            "Hãy trả lời trực tiếp, ngắn gọn từ dữ liệu trên. Không gọi lại "
                            "search_bus_timetable; nếu dữ liệu chưa nêu giờ/điểm cần hỏi thì nói rõ."
                        )
                    )
                )
                # The deterministic route and lookup are both complete. A
                # tool-free generation guarantees this path cannot re-enter a
                # model→tool→model loop for already-resolved timetable data.
                schemas = []
        elif faq_detail_route:
            prefetched, prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "search_knowledge",
                {"query": effective_query},
                metrics,
                resolved_tool_registry,
            )
            if prefetch_hit:
                tool_results.append(str(prefetched))
                messages.append(
                    SystemMessage(
                        content=(
                            "KẾT QUẢ TRA CỨU KB ĐÃ THỰC HIỆN CHO CÂU HỎI NÀY:\n"
                            f"{prefetched}\n\n"
                            "Hãy trả lời ngắn gọn, chỉ dựa trên dữ liệu trên. Nếu dữ liệu "
                            "chưa nêu thông tin cần hỏi thì nói rõ 'tin tuyển dụng chưa ghi rõ'."
                        )
                    )
                )
                schemas = []
        bound = (
            active_llm.bind_tools(schemas)
            if schemas and hasattr(active_llm, "bind_tools")
            else active_llm
        )
        messages.append(HumanMessage(content=user_text))
        for _ in range(self.max_iters):
            if metrics is not None:
                metrics["llm_calls"] = metrics.get("llm_calls", 0) + 1
            # Split the LLM path into semaphore-queue wait vs. model inference.
            # Previously a single timer covered both, so a 34s "LLM" p95 was
            # ambiguous between a slow model and self-inflicted throttle wait.
            sem_t0 = time.monotonic()
            try:
                async with sem:
                    sem_wait_ms = int((time.monotonic() - sem_t0) * 1000)
                    model_t0 = time.monotonic()
                    ai, backoff_ms = await _llm_call_with_retry(bound, messages, metrics=metrics)
                    model_ms = int((time.monotonic() - model_t0) * 1000)
            except LLMThrottled:
                raise
            except Exception as exc:
                # Track non-retry-path 429s for observability (Phase 0 metric).
                if _is_429(exc):
                    _record_llm_429()
                    logger.error("llm_429", exc_info=True)
                raise
            iter_total_ms = int((time.monotonic() - sem_t0) * 1000)
            if metrics is not None:
                metrics["llm_invoke_ms"] = metrics.get("llm_invoke_ms", 0) + iter_total_ms
                metrics["llm_queue_ms"] = metrics.get("llm_queue_ms", 0) + sem_wait_ms
                # Exclude the 429 backoff sleep from model inference so the split
                # stays clean: llm_model_ms = actual ainvoke time only. The
                # backoff is surfaced separately so the dashboard can attribute it.
                metrics["llm_model_ms"] = metrics.get("llm_model_ms", 0) + (model_ms - backoff_ms)
                if backoff_ms > 0:
                    metrics["llm_backoff_ms"] = metrics.get("llm_backoff_ms", 0) + backoff_ms
                metrics["llm_call_ms"].append(model_ms - backoff_ms)
            # Live Redis counter tracks the full LLM path (queue + model) — the
            # right number for the "is the LLM path slow right now?" live tile.
            _record_llm_latency(iter_total_ms)
            # Phase 6: capture token usage + cost from the response.usage block.
            usage = _record_token_usage(
                getattr(ai, "usage_metadata", None)
                or getattr(ai, "response_metadata", {}).get("token_usage")
            )
            if metrics is not None and usage.total_tokens > 0:
                metrics["prompt_tokens"] = metrics.get("prompt_tokens", 0) + usage.prompt_tokens
                metrics["completion_tokens"] = (
                    metrics.get("completion_tokens", 0) + usage.completion_tokens
                )
                metrics["cached_tokens"] = metrics.get("cached_tokens", 0) + usage.cached_tokens
            logger.info("llm_invoke", extra={"llm_latency_ms": iter_total_ms})
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None)
            if not calls:
                return _ground_reply(ai.content, tool_results)
            if metrics is not None:
                metrics["tool_calls"] = metrics.get("tool_calls", 0) + len(calls)
                metrics["tool_rounds"] = metrics.get("tool_rounds", 0) + 1
            tool_t0 = time.monotonic()

            # --- Tool dispatch -------------------------------------------------
            # When the LLM returns multiple tool_calls in one response, run them
            # concurrently (each on its own DB session via ``make_retrieval``) so
            # the latency is max(t1..tN) instead of t1+t2+..+tN. Sequential
            # fallback when there's only one call or no factory is wired (tests).
            async def _dispatch_one(tc: dict) -> str:
                name = tc.get("name", "")
                args = tc.get("args", {})
                tool_call_t0 = time.monotonic()
                try:
                    if make_retrieval is not None:
                        try:
                            async with make_retrieval() as fresh_retrieval:
                                return await _dispatch_tool(
                                    fresh_retrieval,
                                    embedder,
                                    name,
                                    args,
                                    metrics=metrics,
                                    resolved_registry=resolved_tool_registry,
                                )
                        except Exception:  # noqa: BLE001 — session setup failed → shared
                            logger.warning(
                                "isolated retrieval for tool %s failed, using shared",
                                name,
                                exc_info=True,
                            )
                    return await _dispatch_tool(
                        retrieval,
                        embedder,
                        name,
                        args,
                        metrics=metrics,
                        resolved_registry=resolved_tool_registry,
                    )
                finally:
                    if metrics is not None:
                        breakdown = metrics.setdefault("tool_breakdown", {})
                        breakdown[name] = breakdown.get(name, 0) + int(
                            (time.monotonic() - tool_call_t0) * 1000
                        )

            if len(calls) > 1 and make_retrieval is not None:
                sem = asyncio.Semaphore(get_settings().parallel_tool_max_concurrency)

                async def _bounded(tc: dict) -> str:
                    async with sem:
                        return await _dispatch_one(tc)

                outs = await asyncio.gather(*[_bounded(tc) for tc in calls])
            else:
                outs = [await _dispatch_one(tc) for tc in calls]
            if metrics is not None:
                metrics["tool_ms"] = metrics.get("tool_ms", 0) + int(
                    (time.monotonic() - tool_t0) * 1000
                )

            # asyncio.gather preserves result order, so ToolMessage[i] matches
            # tool_calls[i] exactly — the LLM sees identical context ordering.
            # MiniMax occasionally omits tool_call.id; an empty tool_call_id
            # breaks the OpenAI tool protocol on the next turn. Synthesize one.
            for idx, (tc, out) in enumerate(zip(calls, outs)):
                tool_results.append(str(out))
                messages.append(
                    ToolMessage(
                        content=str(out),
                        tool_call_id=tc.get("id") or f"call_{idx}_{tc.get('name', 'tool')}",
                    )
                )
        final = messages[-1].content if hasattr(messages[-1], "content") else ""
        return _ground_reply(final, tool_results)

    async def direct(self, user_text: str, *, system: str, metrics: dict | None = None) -> str:
        """One model call for a direct-context KB; no schemas, tools, or prefetch."""
        from app.graph.llm_semaphore import get_llm_semaphore
        from langchain_core.messages import HumanMessage, SystemMessage

        sem = get_llm_semaphore()
        if metrics is not None:
            metrics["llm_calls"] = metrics.get("llm_calls", 0) + 1
            metrics["direct_context_llm_calls"] = metrics.get("direct_context_llm_calls", 0) + 1
        sem_t0 = time.monotonic()
        async with sem:
            queue_ms = int((time.monotonic() - sem_t0) * 1000)
            model_t0 = time.monotonic()
            ai, backoff_ms = await _llm_call_with_retry(
                self.llm,
                [SystemMessage(content=system), HumanMessage(content=user_text)],
                metrics=metrics,
            )
            model_ms = int((time.monotonic() - model_t0) * 1000)
        total_ms = int((time.monotonic() - sem_t0) * 1000)
        if metrics is not None:
            metrics["llm_invoke_ms"] = metrics.get("llm_invoke_ms", 0) + total_ms
            metrics["llm_queue_ms"] = metrics.get("llm_queue_ms", 0) + queue_ms
            metrics["llm_model_ms"] = metrics.get("llm_model_ms", 0) + (model_ms - backoff_ms)
        _record_llm_latency(total_ms)
        return str(ai.content or "")


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


def _minimax_chat(
    model: str,
    *,
    temperature: float,
    max_retries: int = 0,
    api_key: str | None = None,
):
    """OpenAI-compatible MiniMax client from settings. Shared construction so
    model / base_url / timeout cannot drift between build_deps and the extractor.

    ``max_retries`` defaults to 0: the agent loop handles 429 explicitly via
    ``_llm_call_with_retry`` (one backoff retry, then LLMThrottled → static
    degradation reply). The openai library's built-in retry would just waste
    time (3× the timeout) on top of that, so it stays off.
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


def _active_llm_provider(
    settings=None,
    *,
    minimax_enabled: bool | None = None,
    openrouter_enabled: bool | None = None,
    default_provider: Literal["minimax", "openrouter"] | None = None,
) -> Literal["minimax", "openrouter"]:
    """Return the single configured LLM provider name for this process.

    Resolution order: explicit ``default_provider`` override, then settings'
    ``llm_default_provider`` if its provider is enabled, then whichever provider
    is enabled. There is no runtime failover — this is called once per client
    build, and switching providers is a deploy-time config change.
    """
    s = settings or get_settings()
    mm_on = getattr(s, "minimax_enable", True) if minimax_enabled is None else minimax_enabled
    or_on = (
        getattr(s, "openrouter_enable", False) if openrouter_enabled is None else openrouter_enabled
    )
    preferred = default_provider or getattr(s, "llm_default_provider", "minimax")
    if preferred == "openrouter" and or_on:
        return "openrouter"
    if preferred == "minimax" and mm_on:
        return "minimax"
    if or_on:
        return "openrouter"
    if mm_on:
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

    Returns a plain ``ChatOpenAI`` for the single configured provider. The
    active provider is resolved once by ``_active_llm_provider`` (default first,
    falling back to whichever is enabled) — switching providers is a deploy-time
    ``LLM_DEFAULT_PROVIDER`` change, not a runtime failover. There is no
    per-call fallback: a failed provider call surfaces directly so the caller
    (worker / safety judge) handles it. Removing the runtime failover wrapper
    keeps the client stateless and safe to cache across turns.
    """
    s = get_settings()
    provider = _active_llm_provider(
        s,
        minimax_enabled=minimax_enabled,
        openrouter_enabled=openrouter_enabled,
        default_provider=default_provider,
    )

    if provider == "openrouter":
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
        return _openrouter_chat(
            model,
            temperature=temperature,
            timeout=timeout,
            json_mode=json_mode,
            api_key=resolved_openrouter_key,
        )

    # minimax
    resolved_minimax_key = minimax_api_key or s.minimax_api_key
    if role == "digest":
        if not resolved_minimax_key:
            raise RuntimeError("MINIMAX_API_KEY is required for MiniMax JSON generation")
        from langchain_openai import ChatOpenAI

        kwargs = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
        return ChatOpenAI(
            model=s.minimax_digest_model or s.minimax_agent_model,
            api_key=resolved_minimax_key,
            base_url=s.minimax_base_url,
            timeout=s.minimax_digest_timeout,
            temperature=temperature,
            **kwargs,
        )
    model = s.minimax_agent_model if role == "agent" else s.minimax_safety_model
    return _minimax_chat(
        model,
        temperature=temperature,
        api_key=resolved_minimax_key,
    )
