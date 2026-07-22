"""LLM/embedder clients + MiniMax/OpenRouter agent/safety/digest factories.

Heavy SDKs (google-genai, langchain-openai / langchain-core) are imported LAZILY inside
methods so importing this module stays cheap and free of optional-dependency failures at
import time. Tool schemas + dispatch live in ``schemas.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from functools import lru_cache
from typing import Literal

from app.core.config import get_settings
from app.graph.schemas import _dispatch_tool
from app.graph.usage import record_token_usage as _record_token_usage

logger = logging.getLogger(__name__)

_VACANCY_LOOKUP_UNAVAILABLE_REPLY = (
    "Hiện tôi chưa thể kiểm tra thông tin tuyển dụng. Bạn vui lòng thử lại sau nhé."
)
_ACTIVE_JOB_LOOKUP_PREFIX = "ACTIVE_JOB_LOOKUP_JSON="
_ACTIVE_JOB_LOOKUP_STATUSES = frozenset({"matched", "no_match", "catalog_empty", "unavailable"})
_REASONING_RESPONSE_FIELDS = ("reasoning_details", "reasoning_content", "reasoning")
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>(.*?)</think\s*>", re.IGNORECASE | re.DOTALL)


def _reasoning_text_from_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(
            part for item in value if (part := _reasoning_text_from_value(item))
        ).strip()
    if isinstance(value, dict):
        for key in ("text", "reasoning", "summary"):
            if key in value and (text := _reasoning_text_from_value(value[key])):
                return text
    return ""


def _extract_returned_reasoning(ai: object) -> str | None:
    """Extract provider-returned reasoning without including the final answer."""
    additional_kwargs = getattr(ai, "additional_kwargs", {})
    if isinstance(additional_kwargs, dict):
        for key in _REASONING_RESPONSE_FIELDS:
            if key in additional_kwargs and (
                text := _reasoning_text_from_value(additional_kwargs[key])
            ):
                return text

    try:
        content_blocks = getattr(ai, "content_blocks", [])
    except Exception:  # noqa: BLE001 - provider message compatibility is best-effort
        content_blocks = []
    if isinstance(content_blocks, list):
        reasoning_blocks = [
            block
            for block in content_blocks
            if isinstance(block, dict)
            and (block["type"] if "type" in block else None) in {"reasoning", "thinking"}
        ]
        if text := _reasoning_text_from_value(reasoning_blocks):
            return text

    content = getattr(ai, "content", "")
    if isinstance(content, str):
        blocks = [match.strip() for match in _THINK_BLOCK_RE.findall(content) if match.strip()]
        if blocks:
            return "\n\n".join(blocks)
        opening = re.search(r"<think\b[^>]*>", content, re.IGNORECASE)
        if opening and (unfinished := content[opening.end() :].strip()):
            return unfinished
    return None


@lru_cache(maxsize=1)
def _reasoning_chat_class():
    """ChatOpenAI variant that preserves third-party reasoning fields.

    LangChain's generic OpenAI adapter intentionally drops fields such as
    ``reasoning_content`` and ``reasoning_details``. The subclass keeps those
    fields on AIMessage.additional_kwargs and forwards them unchanged on later
    tool-loop requests, as required by MiniMax/OpenRouter interleaved thinking.
    """
    from langchain_core.messages import AIMessage
    from langchain_openai import ChatOpenAI

    class ReasoningPreservingChatOpenAI(ChatOpenAI):
        trace_provider: str = "unknown"

        def _create_chat_result(self, response, generation_info=None):
            response_dict = (
                response
                if isinstance(response, dict)
                else response.model_dump(warnings=False)
            )
            result = super()._create_chat_result(response, generation_info)
            choices = response_dict["choices"] if "choices" in response_dict else []
            for generation, choice in zip(
                result.generations,
                choices or [],
                strict=False,
            ):
                raw_message = choice["message"] if "message" in choice else {}
                if not isinstance(generation.message, AIMessage):
                    continue
                for key in _REASONING_RESPONSE_FIELDS:
                    if key in raw_message and raw_message[key] is not None:
                        generation.message.additional_kwargs[key] = raw_message[key]
            return result

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            source_messages = self._convert_input(input_).to_messages()
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            wire_messages = payload["messages"] if "messages" in payload else None
            if not isinstance(wire_messages, list):
                return payload
            for source, wire in zip(source_messages, wire_messages, strict=False):
                if not isinstance(source, AIMessage) or not isinstance(wire, dict):
                    continue
                for key in _REASONING_RESPONSE_FIELDS:
                    if key in source.additional_kwargs and source.additional_kwargs[key] is not None:
                        wire[key] = source.additional_kwargs[key]
            return payload

    return ReasoningPreservingChatOpenAI

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


def _scope_project_tool_args(name: str, args: dict, project_slug: str | None) -> dict:
    """Force project-aware tools to the conversation's focused Project."""
    scoped = dict(args)
    if not project_slug:
        return scoped
    if name in {"search_knowledge", "list_active_jobs", "get_product_features"}:
        scoped["project_slug"] = project_slug
    return scoped


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


def _active_job_safe_reply(tool_result: object) -> str | None:
    """Validate one active-job tool payload and return its trusted renderer output."""
    first_line = str(tool_result).partition("\n")[0]
    if not first_line.startswith(_ACTIVE_JOB_LOOKUP_PREFIX):
        return None
    try:
        payload = json.loads(first_line.removeprefix(_ACTIVE_JOB_LOOKUP_PREFIX))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload["status"] if "status" in payload else None
    jobs = payload["jobs"] if "jobs" in payload else None
    safe_reply = payload["safe_reply"] if "safe_reply" in payload else None
    if status not in _ACTIVE_JOB_LOOKUP_STATUSES or not isinstance(jobs, list):
        return None
    if status == "matched":
        if not jobs or any(
            not isinstance(job, dict)
            or not isinstance(job["id"] if "id" in job else None, str)
            or not isinstance(job["title"] if "title" in job else None, str)
            for job in jobs
        ):
            return None
    elif jobs:
        return None
    if not isinstance(safe_reply, str) or not safe_reply.strip():
        return None
    return safe_reply.strip()


def _ground_reply(reply: str, tool_results: list[str], *, trace_sink=None) -> str:
    """Validate LLM prose against surfaced evidence without replacing it.

    Structured job payloads inform the model but never become a separately
    rendered final answer. This keeps every normal recruitment answer on the
    LLM route while retaining the job-ID hallucination guard.
    """
    for tool_result in reversed(tool_results or []):
        first_line = str(tool_result).partition("\n")[0]
        if not first_line.startswith(_ACTIVE_JOB_LOOKUP_PREFIX):
            continue
        if _active_job_safe_reply(tool_result) is None:
            logger.warning("active-job tool returned malformed grounding payload")

    try:
        from app.core.config import get_settings

        if not getattr(get_settings(), "grounding_check_enabled", True):
            if trace_sink is not None:
                trace_sink.record_decision("grounding_verdict", "skipped")
            return reply
        from app.graph.grounding import (
            extract_surfaced_entities,
            extract_surfaced_job_ids,
            validate_grounding,
        )

        surfaced = extract_surfaced_job_ids(tool_results)
        surfaced_entities = extract_surfaced_entities(tool_results)
        result = validate_grounding(reply, surfaced, surfaced_entities)
        if not result.is_grounded:
            if trace_sink is not None:
                trace_sink.record_decision("grounding_verdict", "sanitized")
            logger.warning(
                "grounding_hallucination_stripped: %s cited ids, %s unsupported entities",
                len(result.hallucinated_ids),
                len(result.unsupported_entities),
            )
            return result.sanitized_reply
        if trace_sink is not None:
            trace_sink.record_decision("grounding_verdict", "grounded")
        return reply
    except Exception:  # noqa: BLE001
        if trace_sink is not None:
            trace_sink.record_decision("grounding_verdict", "skipped")
        logger.debug("grounding check skipped (non-fatal)", exc_info=True)
        return reply


def _negative_job_authority(tool_results: list[str]) -> str | None:
    """Return the trusted abstention text for a negative active-job lookup."""
    for tool_result in reversed(tool_results or []):
        first_line = str(tool_result).partition("\n")[0]
        if not first_line.startswith(_ACTIVE_JOB_LOOKUP_PREFIX):
            continue
        try:
            payload = json.loads(first_line.removeprefix(_ACTIVE_JOB_LOOKUP_PREFIX))
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("status") == "matched":
            return None
        safe_reply = _active_job_safe_reply(tool_result)
        return safe_reply
    return None


def _negative_job_reply_is_consistent(reply: str) -> bool:
    """Fast semantic guard; uncertain negative replies go through one LLM rewrite.

    Precedence: a negation marker anywhere in the reply wins over affirmative
    vocabulary. Real abstention replies routinely combine both — e.g.
    "Hiện chưa có vị trí nào đang tuyển" contains ``chua co`` (negative) AND
    ``dang tuyen`` / ``co vi tri`` (affirmative, appearing inside the negated
    phrase and in the offer to check other openings). Checking affirmative
    markers first discarded those grounded replies and forced a wasteful — and
    user-visible — ``direct()`` rewrite that produced the generic
    "chưa thể xác minh" fallback. Only when no negation is present does an
    affirmative marker indicate the model ignored the negative authority.
    """
    normalized = _normalize_query_hint(reply)
    negative = (
        "chua co",
        "chua tim",
        "chua the",
        "khong co",
        "khong con",
        "khong tim",
        "khong tuyen",
        "hien chua",
    )
    if any(marker in normalized for marker in negative):
        return True
    affirmative = (
        "dang tuyen",
        "con tuyen",
        "co viec",
        "co vi tri",
        "tuyen vi tri",
        "luong ",
    )
    if any(marker in normalized for marker in affirmative):
        return False
    return False


def _matched_job_authority(tool_results: list[str]) -> tuple[str, str] | None:
    """Return the matched tool payload and its trusted human-readable summary."""
    for tool_result in reversed(tool_results or []):
        first_line = str(tool_result).partition("\n")[0]
        if not first_line.startswith(_ACTIVE_JOB_LOOKUP_PREFIX):
            continue
        try:
            payload = json.loads(first_line.removeprefix(_ACTIVE_JOB_LOOKUP_PREFIX))
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("status") != "matched":
            return None
        safe_reply = _active_job_safe_reply(tool_result)
        if safe_reply is None:
            return None
        return first_line, safe_reply
    return None


def _matched_job_reply_is_consistent(reply: str, authority_payload: str) -> bool:
    """Reject invented numeric claims while preserving the normal two-call path."""
    claimed_numbers = set(re.findall(r"(?<![\w-])\d+(?![\w-])", reply))
    if not claimed_numbers:
        return True
    authority_numbers = set(re.findall(r"(?<![\w-])\d+(?![\w-])", authority_payload))
    return claimed_numbers <= authority_numbers


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
        required_tool: str | None = None,
        required_tool_args: dict | None = None,
        forced_project_slug: str | None = None,
        retry_empty_generation: bool = False,
        trace_sink=None,
    ) -> str:
        from app.graph.llm_semaphore import LLMThrottled, get_llm_semaphore
        from app.graph.schemas import filter_tool_schemas

        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        active_llm = self.fast_llm if (use_fast and self.fast_llm is not None) else self.llm
        if trace_sink is not None:
            trace_sink.record_decision("model_selected", "fast" if use_fast else "primary")
        if trace_sink is not None and required_tool is not None:
            trace_sink.record_decision("required_tool_selected", required_tool)
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

        def scoped_args(name: str, args: dict) -> dict:
            return _scope_project_tool_args(name, args, forced_project_slug)

        knowledge_lookup_route = allowed_tools == ("search_knowledge",)
        timetable_route = allowed_tools == ("search_bus_timetable",)
        faq_detail_route = allowed_tools == (
            "get_product_features",
            "search_knowledge",
        )
        # Initialized here so the post-generation prefetched_tools guard below
        # can read it unconditionally, even when faq_detail_route did not run.
        # Set to True only when a focused faq_detail turn prefetched
        # get_product_features in parallel and the lookup hit.
        faq_detail_features_hit = False
        if (
            _should_prefetch_knowledge(effective_query)
            and not knowledge_lookup_route
            and not timetable_route
            and not faq_detail_route
        ):
            try:
                if trace_sink is not None:
                    trace_sink.record_tool_selection("search_knowledge", selected_by="policy")
                prefetched = await _dispatch_tool(
                    retrieval,
                    embedder,
                    "search_knowledge",
                    scoped_args("search_knowledge", {"query": effective_query}),
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
        if knowledge_lookup_route:
            if trace_sink is not None:
                trace_sink.record_tool_selection("search_knowledge", selected_by="prefetch")
            prefetched, prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "search_knowledge",
                scoped_args("search_knowledge", {"query": effective_query}),
                metrics,
                resolved_tool_registry,
            )
            tool_results.append(str(prefetched))
            messages.append(
                SystemMessage(
                    content=(
                        "KẾT QUẢ TRA CỨU KB TUYỂN DỤNG ĐÃ THỰC HIỆN CHO TIN NHẮN NÀY:\n"
                        f"{prefetched}\n\n"
                        "Hãy dùng khả năng hiểu ngôn ngữ của bạn để trả lời tự nhiên bằng tiếng "
                        "Việt, nhưng chỉ khẳng định công việc, trạng thái tuyển dụng, địa điểm, "
                        "lương hoặc quyền lợi có trong kết quả trên. Nếu kết quả không chứa bằng "
                        "chứng phù hợp, nói rõ chưa tìm thấy thông tin đã xác minh."
                    )
                )
            )
            # Retrieval has already run against the Agent's assigned KB. Keep
            # generation to one evidence-grounded LLM call instead of asking the
            # model to repeat the same search in a second tool round.
            schemas = []
        elif timetable_route:
            if trace_sink is not None:
                trace_sink.record_tool_selection("search_bus_timetable", selected_by="prefetch")
            prefetched, prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "search_bus_timetable",
                scoped_args(
                    "search_bus_timetable",
                    {"company": "", "question": effective_query},
                ),
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
            if trace_sink is not None:
                trace_sink.record_tool_selection("search_knowledge", selected_by="prefetch")
            # A focused turn may combine the project feature catalog with RAG evidence.
            # EXPLORE mode deliberately stays RAG-only: loading every project's full
            # feature catalog would violate the bounded-context invariant and grow work
            # and prompt size with the total project count.
            focused_slug = forced_project_slug or None
            sem_pf = asyncio.Semaphore(get_settings().parallel_tool_max_concurrency)

            async def _bounded_prefetch(name: str, args: dict) -> tuple[object, bool]:
                async with sem_pf:
                    try:
                        async with make_retrieval() as fresh_retrieval:
                            return await _prefetch_tool(
                                fresh_retrieval,
                                embedder,
                                name,
                                args,
                                metrics,
                                resolved_tool_registry,
                            )
                    except Exception:  # noqa: BLE001 — never reuse shared session concurrently
                        logger.warning("isolated prefetch retrieval for %s failed", name, exc_info=True)
                        return "", False

            if focused_slug:
                if trace_sink is not None:
                    trace_sink.record_tool_selection(
                        "get_product_features", selected_by="prefetch"
                    )
                knowledge_args = scoped_args(
                    "search_knowledge", {"query": effective_query}
                )
                features_args = scoped_args(
                    "get_product_features", {"project_slug": focused_slug}
                )
                if make_retrieval is not None:
                    outcomes = await asyncio.gather(
                        _bounded_prefetch("search_knowledge", knowledge_args),
                        _bounded_prefetch("get_product_features", features_args),
                    )
                    (prefetched, prefetch_hit), (features, features_hit) = outcomes
                else:
                    # Web-chat builds dependencies around one request-scoped
                    # AsyncSession. Keep these calls sequential when no isolated
                    # retrieval factory exists; AsyncSession is not concurrency-safe.
                    prefetched, prefetch_hit = await _prefetch_tool(
                        retrieval,
                        embedder,
                        "search_knowledge",
                        knowledge_args,
                        metrics,
                        resolved_tool_registry,
                    )
                    features, features_hit = await _prefetch_tool(
                        retrieval,
                        embedder,
                        "get_product_features",
                        features_args,
                        metrics,
                        resolved_tool_registry,
                    )
            else:
                prefetched, prefetch_hit = await _prefetch_tool(
                    retrieval,
                    embedder,
                    "search_knowledge",
                    scoped_args("search_knowledge", {"query": effective_query}),
                    metrics,
                    resolved_tool_registry,
                )
                features = None
                features_hit = False
            if prefetch_hit:
                tool_results.append(str(prefetched))
                if features_hit:
                    tool_results.append(str(features))
                    messages.append(
                        SystemMessage(
                            content=(
                                "KẾT QUẢ TRA CỨU CHO CÂU HỎI NÀY:\n"
                                "[ĐẶC ĐIỂM SẢN PHẨM — nguồn chính xác nhất]\n"
                                f"{features}\n\n"
                                "[TRA CỨU KB — thông tin bổ sung]\n"
                                f"{prefetched}\n\n"
                                "Hãy trả lời ngắn gọn, ưu tiên dữ liệu đặc điểm sản phẩm trên. "
                                "Với mục [CHƯA RÕ] hoặc dự án không có trong dữ liệu, nói rõ "
                                "'chưa ghi rõ' hoặc 'chưa có thông tin đã xác minh'; KHÔNG bịa "
                                "thông tin cho dự án không có bằng chứng."
                            )
                        )
                    )
                else:
                    messages.append(
                        SystemMessage(
                            content=(
                                "KẾT QUẢ TRA CỨU KB ĐÃ THỰC HIỆN CHO CÂU HỎI NÀY:\n"
                                f"{prefetched}\n\n"
                                "Hãy trả lời ngắn gọn, chỉ dựa trên dữ liệu trên. Nếu dữ liệu "
                                "chưa nêu thông tin cần hỏi thì nói rõ 'chưa có thông tin đã "
                                "xác minh'; KHÔNG bịa thông tin cho dự án không có bằng chứng."
                            )
                        )
                    )
                schemas = []
            faq_detail_features_hit = features_hit
        if schemas and hasattr(active_llm, "bind_tools"):
            bound = (
                active_llm.bind_tools(schemas, tool_choice=required_tool)
                if required_tool
                else active_llm.bind_tools(schemas)
            )
        else:
            bound = active_llm
        # Each prefetch route (knowledge_lookup_route / timetable_route /
        # faq_detail_route) may eagerly run its authority tool above and then set
        # schemas=[] to skip the model-driven tool-dispatch loop. The
        # post-generation guard at the bottom (`if required_tool and not
        # required_tool_called:`) would otherwise discard the grounded answer and
        # fall back to the "chưa thể truy xuất" reply — even though the evidence
        # was retrieved and surfaced. Record which tool each prefetch actually ran
        # AND hit, and seed the flag only when `required_tool` matches one of those
        # hits. Gating on the hit (not just the route) matters: a KB miss leaves
        # the flag False so the guard still fires and returns the safe fallback
        # instead of an ungrounded or empty reply. prefetch_hit is bound inside
        # whichever route branch ran above; the leading route flag short-circuits
        # so it is never evaluated when no route is active. (Today only
        # knowledge_lookup_route pairs with required_tool="search_knowledge" from
        # the focused-RAG runner branch; the other routes receive
        # required_tool=None.)
        prefetched_tools: set[str] = set()
        if knowledge_lookup_route and prefetch_hit:
            prefetched_tools.add("search_knowledge")
        if timetable_route and prefetch_hit:
            prefetched_tools.add("search_bus_timetable")
        if faq_detail_route and prefetch_hit:
            prefetched_tools.add("search_knowledge")
            # Focused faq_detail turns also prefetch get_product_features in
            # parallel; record it so required_tool guards recognize it as run.
            if faq_detail_features_hit:
                prefetched_tools.add("get_product_features")
        required_tool_called = bool(
            required_tool and required_tool in prefetched_tools
        )
        # True only when ``list_active_jobs`` was actually dispatched in this turn.
        # The authority-override branches below (``_negative_job_authority`` /
        # ``_matched_job_authority``) sanity-check the LLM's reply against the
        # authoritative job evidence, and on a mismatch replace it with a blind
        # ``self.direct()`` call that has no tool context. Without this gate the
        # override can misfire on turns where the model called ``search_knowledge``
        # (or any tool whose result happens to contain the ``ACTIVE_JOB_LOOKUP_JSON``
        # prefix) and discard a perfectly grounded reply from another tool path.
        authority_tool_dispatched = bool(
            required_tool == "list_active_jobs" and required_tool_called
        )
        empty_retry_available = retry_empty_generation
        retrying_empty_generation = False
        iterations_remaining = self.max_iters
        messages.append(HumanMessage(content=user_text))
        while iterations_remaining > 0:
            iterations_remaining -= 1
            if metrics is not None:
                metrics["llm_calls"] = metrics.get("llm_calls", 0) + 1
            was_empty_retry = retrying_empty_generation
            invocation_llm = active_llm if was_empty_retry else bound
            # Split the LLM path into semaphore-queue wait vs. model inference.
            # Previously a single timer covered both, so a 34s "LLM" p95 was
            # ambiguous between a slow model and self-inflicted throttle wait.
            sem_t0 = time.monotonic()
            try:
                async with sem:
                    sem_wait_ms = int((time.monotonic() - sem_t0) * 1000)
                    model_t0 = time.monotonic()
                    ai, backoff_ms = await _llm_call_with_retry(
                        invocation_llm, messages, metrics=metrics
                    )
                    model_ms = int((time.monotonic() - model_t0) * 1000)
            except LLMThrottled:
                if retrying_empty_generation:
                    if metrics is not None:
                        metrics["generation_retry_failure"] = "throttled"
                    return ""
                raise
            except Exception as exc:
                if retrying_empty_generation:
                    if metrics is not None:
                        metrics["generation_retry_failure"] = type(exc).__name__
                    logger.warning(
                        "empty-generation retry failed error_type=%s",
                        type(exc).__name__,
                    )
                    return ""
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
            retrying_empty_generation = False
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None)
            record_model_turn = getattr(trace_sink, "record_model_turn", None)
            if callable(record_model_turn):
                provider = getattr(active_llm, "trace_provider", "unknown")
                if provider not in {"minimax", "openrouter"}:
                    provider = "unknown"
                model = str(
                    getattr(active_llm, "model_name", None)
                    or getattr(active_llm, "model", None)
                    or "unknown"
                )
                phase = "retry" if was_empty_retry else "tool_request" if calls else "final"
                record_model_turn(
                    phase=phase,
                    provider=provider,
                    model=model,
                    reasoning=_extract_returned_reasoning(ai),
                    tool_names=[call["name"] if "name" in call else "" for call in calls or []],
                )
            if was_empty_retry:
                from app.graph.safety import fast_safety_filter

                # Recovery is deliberately tool-free. Re-run the deterministic
                # safety filter on the retry result and never dispatch tools.
                retry_safety = fast_safety_filter(str(ai.content or ""))
                if retry_safety["safe_to_send"]:
                    return _ground_reply(
                        retry_safety["output"],
                        tool_results,
                        trace_sink=trace_sink,
                    )
                if retry_safety["too_long"]:
                    return _ground_reply(retry_safety["output"], tool_results, trace_sink=trace_sink)
                return _ground_reply("", tool_results, trace_sink=trace_sink)
            if not calls:
                from app.graph.safety import fast_safety_filter

                safety = fast_safety_filter(str(ai.content or ""))
                if (
                    safety["retryable_empty"]
                    and empty_retry_available
                    and (required_tool is None or required_tool_called)
                ):
                    empty_retry_available = False
                    retrying_empty_generation = True
                    iterations_remaining += 1
                    messages.pop()
                    if metrics is not None:
                        metrics["generation_retry_count"] = 1
                        metrics["generation_retry_reason"] = "empty_after_clean"
                    continue
                if required_tool and not required_tool_called:
                    logger.warning("required LLM tool was not called: %s", required_tool)
                    return await self.direct(
                        user_text,
                        system=(
                            "Bạn là tư vấn viên tuyển dụng. Dữ liệu tuyển dụng bắt buộc chưa được "
                            "truy xuất thành công. Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa "
                            "thể kiểm tra, không xác nhận có việc và không bịa dữ liệu."
                        ),
                        metrics=metrics,
                        trace_sink=trace_sink,
                    )
                negative_authority = _negative_job_authority(tool_results)
                if (
                    authority_tool_dispatched
                    and negative_authority is not None
                    and not _negative_job_reply_is_consistent(str(ai.content or ""))
                ):
                    return await self.direct(
                        user_text,
                        system=(
                            "Bạn là tư vấn viên tuyển dụng. Kết quả có thẩm quyền dưới đây xác nhận "
                            "không có việc phù hợp hoặc chưa thể kiểm tra. Hãy diễn đạt tự nhiên bằng "
                            "tiếng Việt, giữ nguyên ý nghĩa, không thêm công việc hay dữ liệu mới:\n\n"
                            f"{negative_authority}"
                        ),
                        metrics=metrics,
                        trace_sink=trace_sink,
                    )
                matched_authority = _matched_job_authority(tool_results)
                if (
                    authority_tool_dispatched
                    and matched_authority is not None
                    and not _matched_job_reply_is_consistent(
                        str(ai.content or ""), matched_authority[0]
                    )
                ):
                    return await self.direct(
                        user_text,
                        system=(
                            "Bạn là tư vấn viên tuyển dụng. Hãy trả lời tự nhiên bằng tiếng Việt "
                            "chỉ từ danh sách việc đã xác minh dưới đây. Không thêm vị trí, số lượng, "
                            "mức lương hoặc địa điểm mới:\n\n"
                            f"{matched_authority[1]}"
                        ),
                        metrics=metrics,
                        trace_sink=trace_sink,
                    )
                return _ground_reply(ai.content, tool_results, trace_sink=trace_sink)
            if metrics is not None:
                metrics["tool_calls"] = metrics.get("tool_calls", 0) + len(calls)
                metrics["tool_rounds"] = metrics.get("tool_rounds", 0) + 1
            tool_t0 = time.monotonic()

            if trace_sink is not None and not callable(
                getattr(trace_sink, "record_model_turn", None)
            ):
                for tool_call in calls:
                    trace_sink.record_tool_selection(tool_call.get("name", ""), selected_by="model")

            # --- Tool dispatch -------------------------------------------------
            # When the LLM returns multiple tool_calls in one response, run them
            # concurrently (each on its own DB session via ``make_retrieval``) so
            # the latency is max(t1..tN) instead of t1+t2+..+tN. Sequential
            # fallback when there's only one call or no factory is wired (tests).
            async def _dispatch_one(tc: dict) -> str:
                name = tc.get("name", "")
                raw_args = (
                    dict(required_tool_args)
                    if name == required_tool and required_tool_args is not None
                    else tc.get("args", {})
                )
                if forced_project_slug and name in {
                    "list_active_projects",
                    "recommend_projects",
                    "recommend_jobs",
                    "search_bus_timetable",
                }:
                    return "Công cụ khám phá nhiều dự án không khả dụng khi cuộc trò chuyện đang tập trung vào một dự án."
                args = scoped_args(name, raw_args)
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
                tool_name = tc["name"] if "name" in tc else ""
                if tool_name == required_tool:
                    required_tool_called = True
                    if tool_name == "list_active_jobs":
                        authority_tool_dispatched = True
                    if _active_job_safe_reply(out) is None:
                        logger.warning("required LLM tool returned invalid evidence: %s", required_tool)
                        return await self.direct(
                            user_text,
                            system=(
                                "Bạn là tư vấn viên tuyển dụng. Kết quả kiểm tra tuyển dụng không "
                                "hợp lệ. Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể xác minh, "
                                "không xác nhận có việc và không bịa dữ liệu."
                            ),
                            metrics=metrics,
                            trace_sink=trace_sink,
                        )
                elif tool_name == "list_active_jobs":
                    # Model called list_active_jobs voluntarily (not as required_tool).
                    authority_tool_dispatched = True
                tool_results.append(str(out))
                messages.append(
                    ToolMessage(
                        content=str(out),
                        tool_call_id=tc.get("id") or f"call_{idx}_{tc.get('name', 'tool')}",
                    )
                )
            if required_tool_called and schemas and hasattr(active_llm, "bind_tools"):
                # Require the authority tool only on the first model round. After
                # evidence is present, allow the model to produce its final turn.
                bound = active_llm.bind_tools(schemas)
        if required_tool and not required_tool_called:
            return await self.direct(
                user_text,
                system=(
                    "Bạn là tư vấn viên tuyển dụng. Không có dữ liệu tuyển dụng đã xác minh cho "
                    "lượt này. Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể kiểm tra, không "
                    "xác nhận có việc và không bịa dữ liệu."
                ),
                metrics=metrics,
                trace_sink=trace_sink,
            )
        final = messages[-1].content if hasattr(messages[-1], "content") else ""
        negative_authority = _negative_job_authority(tool_results)
        if (
            authority_tool_dispatched
            and negative_authority is not None
            and not _negative_job_reply_is_consistent(str(final))
        ):
            return await self.direct(
                user_text,
                system=(
                    "Bạn là tư vấn viên tuyển dụng. Kết quả có thẩm quyền dưới đây xác nhận không "
                    "có việc phù hợp hoặc chưa thể kiểm tra. Hãy diễn đạt tự nhiên bằng tiếng Việt, "
                    "giữ nguyên ý nghĩa, không thêm công việc hay dữ liệu mới:\n\n"
                    f"{negative_authority}"
                ),
                metrics=metrics,
                trace_sink=trace_sink,
            )
        matched_authority = _matched_job_authority(tool_results)
        if (
            authority_tool_dispatched
            and matched_authority is not None
            and not _matched_job_reply_is_consistent(str(final), matched_authority[0])
        ):
            return await self.direct(
                user_text,
                system=(
                    "Bạn là tư vấn viên tuyển dụng. Hãy trả lời tự nhiên bằng tiếng Việt chỉ từ "
                    "danh sách việc đã xác minh dưới đây. Không thêm vị trí, số lượng, mức lương "
                    "hoặc địa điểm mới:\n\n"
                    f"{matched_authority[1]}"
                ),
                metrics=metrics,
                trace_sink=trace_sink,
            )
        return _ground_reply(final, tool_results, trace_sink=trace_sink)

    async def direct(
        self,
        user_text: str,
        *,
        system: str,
        metrics: dict | None = None,
        trace_sink=None,
    ) -> str:
        """One model call for a direct-context KB; no schemas, tools, or prefetch."""
        from app.graph.llm_semaphore import get_llm_semaphore
        from langchain_core.messages import HumanMessage, SystemMessage

        sem = get_llm_semaphore()
        if trace_sink is not None:
            trace_sink.record_decision("model_selected", "direct")
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
        if trace_sink is not None:
            record_model_turn = getattr(trace_sink, "record_model_turn", None)
            if callable(record_model_turn):
                provider = getattr(self.llm, "trace_provider", "unknown")
                if provider not in {"minimax", "openrouter"}:
                    provider = "unknown"
                record_model_turn(
                    phase="direct",
                    provider=provider,
                    model=str(
                        getattr(self.llm, "model_name", None)
                        or getattr(self.llm, "model", None)
                        or "unknown"
                    ),
                    reasoning=_extract_returned_reasoning(ai),
                    tool_names=[],
                )
            trace_sink.record_decision("grounding_verdict", "skipped")
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
    chat_class = _reasoning_chat_class()
    return chat_class(
        model=model,
        api_key=resolved_api_key,
        base_url=s.minimax_base_url,
        timeout=s.minimax_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="minimax",
    )


def _openrouter_chat(
    model: str,
    *,
    temperature: float,
    timeout: int | None = None,
    json_mode: bool = False,
    max_retries: int = 0,
    api_key: str | None = None,
    capture_reasoning: bool = False,
):
    """OpenAI-compatible OpenRouter client from settings."""
    s = get_settings()
    resolved_api_key = api_key or s.openrouter_api_key
    if not resolved_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter chat")
    kwargs = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    if capture_reasoning:
        kwargs["extra_body"] = {
            "reasoning": {"effort": "high", "exclude": False},
        }
    chat_class = _reasoning_chat_class()
    return chat_class(
        model=model,
        api_key=resolved_api_key,
        base_url=s.openrouter_base_url,
        timeout=timeout or s.openrouter_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="openrouter",
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
            capture_reasoning=role == "agent",
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
