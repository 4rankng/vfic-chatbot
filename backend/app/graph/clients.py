"""LLM/embedder clients + MiniMax/OpenRouter agent/extractor/digest factories.

Heavy SDKs (google-genai, langchain-openai / langchain-core) are imported LAZILY inside
methods so importing this module stays cheap and free of optional-dependency failures at
import time. Tool schemas + dispatch live in ``schemas.py``. The former inline
helper families now live beside their single concern: reasoning-field wire
compatibility in ``reasoning_compat.py``, Redis observability counters in
``llm_observability.py``, routed pre-lookup heuristics in ``prefetch.py``,
retry/quota failover in ``provider_failover.py``, and reply grounding +
active-job authority rendering in ``grounding.py``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from app.core.config import get_settings
from app.graph.grounding import (
    active_job_safe_reply as _active_job_safe_reply,
    ground_active_job_reply as _ground_active_job_reply,
    ground_reply as _ground_reply,
)
from app.graph.income_contract import safe_reply_from
from app.graph.llm_observability import _record_llm_429, _record_llm_latency
from app.graph.llm_observability import (
    _RKEY_429 as _RKEY_429,
    _RKEY_INVOKE_COUNT as _RKEY_INVOKE_COUNT,
    _RKEY_INVOKE_MS as _RKEY_INVOKE_MS,
)
from app.graph.prefetch import (
    _prefetch_tool,
    _scope_project_tool_args,
    _should_prefetch_knowledge,
)
from app.graph.provider_failover import (
    _bind_like,
    _is_429,
    _llm_call_streaming_with_retry,
    _llm_call_with_retry,
)
from app.graph.reasoning_compat import (
    _extract_returned_reasoning,
    _reasoning_chat_class,
)
from app.graph.think_strip import extract_text_tool_calls, strip_provider_artifacts
from app.graph.schemas import _dispatch_tool
from app.graph.usage import record_token_usage as _record_token_usage

logger = logging.getLogger(__name__)

ModelRole = Literal["agent", "extractor", "digest"]
# The three configurable providers. "custom" is any OpenAI-compatible endpoint
# the operator supplies (base URL + model ids), e.g. Xiaomi MiMo.
LlmProvider = Literal["minimax", "openrouter", "custom"]


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


# ── Answer-completion guard (provider output cap) ────────────────────────────
# MiniMax M2.x cannot disable thinking and emits its deliberation *inside*
# ``content`` (`` thinking…``), so an operator-configured generation budget
# (``llm_agent_max_tokens``, 0 = no cap and the shipped default) covers reasoning
# AND answer. A cap the think block mostly consumes hands back a half-written
# answer with ``finish_reason=length``; the reply boundary that used to repair a
# cut answer was removed, so a cut would ship verbatim (observed: a route list
# ending mid-word). The lanes therefore COMPLETE a cut answer before it is
# delivered: the model is asked to continue from the exact cut, bounded by
# ``_MAX_ANSWER_CONTINUATIONS`` and by the turn's remaining model-call budget. If
# the provider still stops at the cap, the dangling tail is dropped (bounded to
# the last complete sentence or line), so a candidate never receives a mid-word
# fragment.
_TRUNCATED_FINISH_REASONS = frozenset(
    {"length", "max_tokens", "max_output_tokens", "max_completion_tokens"}
)
_MAX_ANSWER_CONTINUATIONS = 2
_CUT_ANSWER_CONTINUE_INSTRUCTION = (
    "Câu trả lời của bạn vừa bị nhà cung cấp cắt ngang vì chạm hạn mức độ dài. "
    "Hãy viết tiếp NGAY tại đúng chỗ đang dở, không lặp lại phần đã viết, không mở "
    "đầu lại và không lặp lời chào; hoàn thành trọn vẹn câu trả lời cho người lao động."
)
# A repeated seam (the model re-emitting the tail it was handed) is dropped, but
# only when the overlap is long enough and word-aligned on both sides, so
# legitimate repetition inside an answer is never deleted.
_CONTINUATION_OVERLAP_MIN_CHARS = 24
_CONTINUATION_OVERLAP_MAX_CHARS = 400
_ANSWER_SENTENCE_END_CHARS = frozenset(".!?…")
_SEAM_BOUNDARY_CHARS = frozenset(",.;:!?…-")
# How far back a dangling (still-cut) tail may be trimmed, so a long complete
# answer is never gutted by a single missing full stop.
_MAX_DANGLING_TAIL_CHARS = 200


def _answer_was_cut(message) -> bool:
    """True when the provider stopped at its output cap instead of finishing."""
    metadata = getattr(message, "response_metadata", None) or {}
    reason = str(metadata.get("finish_reason") or metadata.get("stop_reason") or "")
    return reason.strip().lower() in _TRUNCATED_FINISH_REASONS


def _should_continue_cut_answer(message, visible: str, used: int) -> bool:
    """Whether a cut answer may be continued instead of shipped half-written."""
    return used < _MAX_ANSWER_CONTINUATIONS and bool(visible.strip()) and _answer_was_cut(message)


def _record_answer_continuation(metrics: dict | None, count: int) -> None:
    """Surface the output-cap repair on the turn's metrics."""
    if metrics is not None:
        metrics["answer_continuations"] = count
        metrics["answer_continuation_reason"] = "output_cap"


def _join_answer_parts(parts: list[str]) -> str:
    """Join the answer rounds of one generation, dropping a repeated seam."""
    joined = ""
    for part in parts:
        if not part:
            continue
        joined = part if not joined else joined + _seam_remainder(joined, part)
    return joined


def _seam_remainder(joined: str, part: str) -> str:
    """``part`` minus its overlap with ``joined``, else ``part`` unchanged."""
    limit = min(len(joined), len(part), _CONTINUATION_OVERLAP_MAX_CHARS)
    for size in range(limit, _CONTINUATION_OVERLAP_MIN_CHARS - 1, -1):
        if not joined.endswith(part[:size]):
            continue
        following = part[size : size + 1]
        if following and not (following.isspace() or following in _SEAM_BOUNDARY_CHARS):
            continue
        preceding = joined[-size - 1 : -size] if size < len(joined) else ""
        if preceding and not (preceding.isspace() or preceding in _SEAM_BOUNDARY_CHARS):
            continue
        return part[size:]
    return part


def _drop_dangling_tail(text: str) -> str:
    """Drop a still-truncated answer's dangling tail.

    Bounded to the last ``_MAX_DANGLING_TAIL_CHARS`` so a complete answer is
    never gutted: cut at the last sentence/line boundary in that window, else at
    the last whitespace, so the delivered text never ends mid-word.
    """
    stripped = text.rstrip()
    if not stripped:
        return text
    start = max(0, len(stripped) - _MAX_DANGLING_TAIL_CHARS)
    for index in range(len(stripped) - 1, start - 1, -1):
        if stripped[index] in _ANSWER_SENTENCE_END_CHARS or stripped[index] == "\n":
            return stripped[: index + 1].rstrip() or text
    for index in range(len(stripped) - 1, start - 1, -1):
        if stripped[index].isspace():
            return stripped[:index].rstrip() or text
    return text


class MiniMaxAgent:
    """Tool-calling agent: loops on MiniMax tool_calls until a final text reply.

    ``fast_llm`` (optional, Phase 5 model tiering): when provided and the caller
    passes ``use_fast=True``, the lightweight model is used instead of the primary
    reasoning model. The runner decides eligibility via ``should_use_fast_model``.

    ``fallback_llms`` (optional): ordered clients for the other configured
    providers, used only when the primary reports rate-limit/quota exhaustion.
    Empty keeps the previous behaviour of degrading to a static reply.
    """

    def __init__(
        self,
        llm,
        embedder,
        max_iters: int | None = None,
        fast_llm=None,
        fallback_llms: list | None = None,
    ) -> None:
        self.llm = llm
        self.embedder = embedder
        self.fast_llm = fast_llm
        self.fallback_llms = list(fallback_llms or [])
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
        on_delta=None,
        on_evidence=None,
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
        # Everything the model was shown before it wrote the reply: the system
        # prompt (persona + admin API guide) and the candidate's own message
        # (history included). The contact guard treats a phone number or e-mail
        # outside this text as an invention.
        contact_evidence = f"{system}\n{user_text}"

        def scoped_args(name: str, args: dict) -> dict:
            return _scope_project_tool_args(name, args, forced_project_slug)

        async def _publish_evidence() -> None:
            """Hand the accumulated tool evidence to the progressive sender.

            Called after every ``tool_results`` append (prefetch and dispatched
            rounds alike): a bubble streamed mid-generation must pass the same
            job-id/entity grounding cross-check as the full reply, so it needs
            the evidence the model had actually seen when that text was produced.
            A snapshot copy is passed so a later append cannot mutate it.
            """
            if on_evidence is not None:
                await on_evidence(list(tool_results))

        knowledge_lookup_route = allowed_tools == ("search_knowledge",)
        timetable_route = allowed_tools == ("search_bus_timetable",)
        income_compare_route = allowed_tools == ("compare_income",)
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
                await _publish_evidence()
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
                dispatch=_dispatch_tool,
            )
            tool_results.append(str(prefetched))
            await _publish_evidence()
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
                dispatch=_dispatch_tool,
            )
            if prefetch_hit:
                tool_results.append(str(prefetched))
                await _publish_evidence()
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
        elif income_compare_route:
            if trace_sink is not None:
                trace_sink.record_tool_selection("compare_income", selected_by="prefetch")
            prefetched, prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "compare_income",
                dict(required_tool_args or {}),
                metrics,
                resolved_tool_registry,
                dispatch=_dispatch_tool,
            )
            if prefetch_hit:
                safe_reply = safe_reply_from(
                    prefetched,
                    expected_target_monthly_vnd=(required_tool_args or {}).get(
                        "target_monthly_vnd"
                    ),
                )
                if safe_reply is not None:
                    if trace_sink is not None:
                        trace_sink.record_decision("grounding_verdict", "grounded")
                    return safe_reply
                logger.warning("compare-income tool returned malformed authority payload")
                prefetch_hit = False
                if metrics is not None:
                    metrics["prefetch_hit"] = False
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
                                dispatch=_dispatch_tool,
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
                        dispatch=_dispatch_tool,
                    )
                    features, features_hit = await _prefetch_tool(
                        retrieval,
                        embedder,
                        "get_product_features",
                        features_args,
                        metrics,
                        resolved_tool_registry,
                        dispatch=_dispatch_tool,
                    )
            else:
                prefetched, prefetch_hit = await _prefetch_tool(
                    retrieval,
                    embedder,
                    "search_knowledge",
                    scoped_args("search_knowledge", {"query": effective_query}),
                    metrics,
                    resolved_tool_registry,
                    dispatch=_dispatch_tool,
                )
                features = None
                features_hit = False
            if prefetch_hit:
                tool_results.append(str(prefetched))
                await _publish_evidence()
                if features_hit:
                    tool_results.append(str(features))
                    await _publish_evidence()
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
        if income_compare_route and prefetch_hit:
            prefetched_tools.add("compare_income")
        if faq_detail_route and prefetch_hit:
            prefetched_tools.add("search_knowledge")
            # Focused faq_detail turns also prefetch get_product_features in
            # parallel; record it so required_tool guards recognize it as run.
            if faq_detail_features_hit:
                prefetched_tools.add("get_product_features")
        required_tool_called = bool(
            required_tool and required_tool in prefetched_tools
        )
        authority_tool_dispatched = bool(
            required_tool == "list_active_jobs" and required_tool_called
        )
        iterations_remaining = self.max_iters
        empty_retry_available = retry_empty_generation
        retrying_empty_generation = False
        # Answer rounds of this turn (see the answer-completion guard above):
        # normally one, more when the provider cut an answer at its output cap.
        answer_parts: list[str] = []
        answer_continuations = 0
        continuing_answer = False
        last_round_cut = False

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

        messages.append(HumanMessage(content=user_text))
        while iterations_remaining > 0:
            iterations_remaining -= 1
            if metrics is not None:
                metrics["llm_calls"] = metrics.get("llm_calls", 0) + 1
            # This iteration is a recovery attempt only if the previous round
            # asked for one. Recovery is deliberately tool-free: the reply came
            # back empty *because* the tool round consumed the answer budget, so
            # re-asking without tools is what produces prose.
            was_empty_retry = retrying_empty_generation
            # A recovery round and an answer-continuation round are both
            # tool-free: a cut answer is continued as prose, never by re-entering
            # tool dispatch.
            tool_free_round = was_empty_retry or continuing_answer
            invocation_llm = active_llm if tool_free_round else bound
            # Split the LLM path into semaphore-queue wait vs. model inference.
            # Previously a single timer covered both, so a 34s "LLM" p95 was
            # ambiguous between a slow model and self-inflicted throttle wait.
            sem_t0 = time.monotonic()
            try:
                async with sem:
                    sem_wait_ms = int((time.monotonic() - sem_t0) * 1000)
                    model_t0 = time.monotonic()
                    # The failover client must carry the same tool bindings as
                    # the primary, or a mid-loop switch would lose the tools the
                    # conversation already depends on.
                    _fallback_bounds = [
                        _bind_like(client, schemas, bound_primary=not tool_free_round)
                        for client in self.fallback_llms
                    ]
                    if on_delta is not None:
                        # Progressive delivery: forward answer text as it is
                        # produced so the first complete bubble can be sent
                        # before the generation finishes. A tool-request round
                        # emits no visible text, so nothing is sent for it.
                        ai, backoff_ms = await _llm_call_streaming_with_retry(
                            invocation_llm,
                            messages,
                            on_delta=on_delta,
                            metrics=metrics,
                            fallback_bounds=_fallback_bounds,
                        )
                    else:
                        ai, backoff_ms = await _llm_call_with_retry(
                            invocation_llm,
                            messages,
                            metrics=metrics,
                            fallback_bounds=_fallback_bounds,
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
                    # Recovery is best-effort: a failed retry hands the turn back
                    # to the runner's fallback instead of a provider error.
                    if metrics is not None:
                        metrics["generation_retry_failure"] = type(exc).__name__
                    logger.warning(
                        "empty-generation retry failed error_type=%s",
                        type(exc).__name__,
                    )
                    return ""
                # Track provider 429s for observability (Phase 0 metric).
                if _is_429(exc):
                    await _record_llm_429()
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
            await _record_llm_latency(iter_total_ms)
            # Phase 6: capture token usage + cost from the response.usage block.
            usage = await _record_token_usage(
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
            last_round_cut = _answer_was_cut(ai)
            record_model_turn = getattr(trace_sink, "record_model_turn", None)
            if callable(record_model_turn):
                provider = getattr(active_llm, "trace_provider", "unknown")
                # "fallback" is the admin-configured custom provider
                # (schema literal DecisionTraceProvider); without it here a
                # custom-provider turn is recorded as "unknown".
                if provider not in {"minimax", "openrouter", "fallback"}:
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
                # Never dispatch tools on a recovery round; the reply policy that
                # used to gate this is gone, so the recovery simply ships the
                # generated prose (thinking stripped).
                visible_round = strip_provider_artifacts(str(ai.content or ""))
                answer_parts.append(visible_round)
                if _should_continue_cut_answer(ai, visible_round, answer_continuations):
                    answer_continuations += 1
                    continuing_answer = True
                    messages.append(SystemMessage(content=_CUT_ANSWER_CONTINUE_INSTRUCTION))
                    _record_answer_continuation(metrics, answer_continuations)
                    continue
                answer = _join_answer_parts(answer_parts)
                if _answer_was_cut(ai):
                    # Still cut after the continuation budget: drop the dangling
                    # fragment instead of a mid-word tail.
                    answer = _drop_dangling_tail(answer)
                return _ground_reply(
                    answer,
                    tool_results,
                    allowed_text=contact_evidence,
                    trace_sink=trace_sink,
                )
            if not calls:
                raw_content = str(ai.content or "")
                text_calls = extract_text_tool_calls(raw_content)
                if text_calls:
                    # The provider wrote its call as content markup instead of a
                    # tool_calls block (production delivered the whole
                    # <invoke name="search_knowledge"> block to a candidate). Run
                    # it through the same dispatch and guards as a structured
                    # call, hand the result back to the model and let it answer
                    # now that it has the data. The markup never reaches a reply:
                    # this path consumes it, and the boundary strips whatever
                    # remains.
                    logger.warning(
                        "provider emitted %d tool call(s) as text: %s",
                        len(text_calls),
                        ", ".join(call["name"] for call in text_calls),
                    )
                    if trace_sink is not None:
                        for call in text_calls:
                            trace_sink.record_tool_selection(
                                call["name"], selected_by="model_text"
                            )
                    text_outs = [await _dispatch_one(call) for call in text_calls]
                    for call, out in zip(text_calls, text_outs):
                        tool_results.append(str(out))
                        await _publish_evidence()
                        if call["name"] == required_tool:
                            required_tool_called = True
                        # OpenAI tool protocol needs an id; the synthesized one
                        # matches the parsed order and is never shown to anyone.
                        messages.append(
                            ToolMessage(
                                content=str(out),
                                tool_call_id=str(call["id"]),
                                name=str(call["name"]),
                            )
                        )
                    if metrics is not None:
                        metrics["tool_calls"] = metrics.get("tool_calls", 0) + len(text_calls)
                        metrics["tool_rounds"] = metrics.get("tool_rounds", 0) + 1
                        metrics["text_tool_calls"] = metrics.get("text_tool_calls", 0) + len(
                            text_calls
                        )
                    continue
                visible_round = strip_provider_artifacts(raw_content)
                if (
                    not visible_round.strip()
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
                answer_parts.append(visible_round)
                if _should_continue_cut_answer(ai, visible_round, answer_continuations):
                    answer_continuations += 1
                    continuing_answer = True
                    messages.append(SystemMessage(content=_CUT_ANSWER_CONTINUE_INSTRUCTION))
                    _record_answer_continuation(metrics, answer_continuations)
                    logger.warning(
                        "answer cut by the provider output cap; continuing %d/%d",
                        answer_continuations,
                        _MAX_ANSWER_CONTINUATIONS,
                    )
                    continue
                # Active-job authority turns fail closed to the tool-rendered
                # safe reply. This removes the former third LLM rewrite while
                # avoiding partial regex validation of titles, locations,
                # vacancy counts, and salary formats. Other tools retain the
                # sanitize-only ID/entity grounding path.
                final_reply = _join_answer_parts(answer_parts)
                if _answer_was_cut(ai):
                    # The provider stopped at the cap again: drop the dangling
                    # fragment so the candidate never reads a mid-word tail.
                    final_reply = _drop_dangling_tail(final_reply)
                if authority_tool_dispatched:
                    final_reply = _ground_active_job_reply(final_reply, tool_results)
                return _ground_reply(
                    final_reply,
                    tool_results,
                    allowed_text=contact_evidence,
                    trace_sink=trace_sink,
                )
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
                    authority_valid = True
                    if required_tool == "compare_income":
                        safe_reply = safe_reply_from(
                            out,
                            expected_target_monthly_vnd=(required_tool_args or {}).get(
                                "target_monthly_vnd"
                            ),
                        )
                        if safe_reply is not None:
                            return safe_reply
                        authority_valid = False
                    elif required_tool == "list_active_jobs":
                        authority_valid = _active_job_safe_reply(out) is not None
                    if not authority_valid:
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
                if tool_name == "list_active_jobs":
                    authority_tool_dispatched = True
                tool_results.append(str(out))
                messages.append(
                    ToolMessage(
                        content=str(out),
                        tool_call_id=tc.get("id") or f"call_{idx}_{tc.get('name', 'tool')}",
                    )
                )
            # One publish per dispatch round: the next model call is the one that
            # can stream a bubble, and by then every result above is in hand.
            await _publish_evidence()
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
        if answer_parts:
            # A continued answer outranks the last message: exhaustion after a
            # cut-answer continuation must never ship the instruction text.
            final = _join_answer_parts(answer_parts)
            if last_round_cut:
                final = _drop_dangling_tail(final)
        else:
            final = messages[-1].content if hasattr(messages[-1], "content") else ""
        if authority_tool_dispatched:
            final = _ground_active_job_reply(str(final or ""), tool_results)
        # Apply the same deterministic authority boundary on loop exhaustion;
        # no third LLM rewrite call is needed.
        return _ground_reply(
            final,
            tool_results,
            allowed_text=contact_evidence,
            trace_sink=trace_sink,
        )

    async def direct(
        self,
        user_text: str,
        *,
        system: str,
        metrics: dict | None = None,
        trace_sink=None,
    ) -> str:
        """One model call for a direct-context KB; no schemas, tools, or prefetch.

        A provider that stops at its output cap is continued exactly as in
        ``agent`` (see the answer-completion guard above): this lane produces
        candidate-visible prose too, so a cut answer must never ship.
        """
        from app.graph.llm_semaphore import get_llm_semaphore
        from langchain_core.messages import HumanMessage, SystemMessage

        sem = get_llm_semaphore()
        if trace_sink is not None:
            trace_sink.record_decision("model_selected", "direct")
        messages = [SystemMessage(content=system), HumanMessage(content=user_text)]
        answer_parts: list[str] = []
        answer_continuations = 0
        ai = None
        for _round in range(_MAX_ANSWER_CONTINUATIONS + 1):
            if metrics is not None:
                metrics["llm_calls"] = metrics.get("llm_calls", 0) + 1
                metrics["direct_context_llm_calls"] = metrics.get("direct_context_llm_calls", 0) + 1
            sem_t0 = time.monotonic()
            async with sem:
                queue_ms = int((time.monotonic() - sem_t0) * 1000)
                model_t0 = time.monotonic()
                ai, backoff_ms = await _llm_call_with_retry(
                    self.llm,
                    messages,
                    metrics=metrics,
                    fallback_bounds=self.fallback_llms,
                )
                model_ms = int((time.monotonic() - model_t0) * 1000)
            total_ms = int((time.monotonic() - sem_t0) * 1000)
            if metrics is not None:
                metrics["llm_invoke_ms"] = metrics.get("llm_invoke_ms", 0) + total_ms
                metrics["llm_queue_ms"] = metrics.get("llm_queue_ms", 0) + queue_ms
                metrics["llm_model_ms"] = metrics.get("llm_model_ms", 0) + (model_ms - backoff_ms)
            await _record_llm_latency(total_ms)
            if trace_sink is not None:
                record_model_turn = getattr(trace_sink, "record_model_turn", None)
                if callable(record_model_turn):
                    provider = getattr(self.llm, "trace_provider", "unknown")
                    # "fallback" is the admin-configured custom provider
                    # (schema literal DecisionTraceProvider); without it here a
                    # custom-provider turn is recorded as "unknown".
                    if provider not in {"minimax", "openrouter", "fallback"}:
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
            visible_round = strip_provider_artifacts(str(ai.content or ""))
            answer_parts.append(visible_round)
            if not _should_continue_cut_answer(ai, visible_round, answer_continuations):
                break
            answer_continuations += 1
            messages.append(SystemMessage(content=_CUT_ANSWER_CONTINUE_INSTRUCTION))
            _record_answer_continuation(metrics, answer_continuations)
            logger.warning(
                "direct answer cut by the provider output cap; continuing %d/%d",
                answer_continuations,
                _MAX_ANSWER_CONTINUATIONS,
            )
        if trace_sink is not None:
            trace_sink.record_decision("grounding_verdict", "skipped")
        answer = _join_answer_parts(answer_parts)
        if ai is not None and _answer_was_cut(ai):
            # Still cut after the continuation budget: drop the dangling
            # fragment rather than send a mid-word tail.
            answer = _drop_dangling_tail(answer)
        return answer


_REASONING_MODES = ("off", "low", "default")


def _resolve_reasoning_mode(explicit: str | None = None) -> str:
    """Resolve the reasoning mode: explicit arg, then settings, else ``off``.

    Default is ``off`` — the chain-of-thought is never shown to the candidate and
    only inflates wall time (measured: disabling it on the MiMo token plan cut a
    12k-token turn from 6,925 ms to 5,227 ms at equal answer length). Read via
    ``getattr`` so the behaviour is live before the settings field is added, and a
    deployment that wants the old behaviour can set ``LLM_REASONING_MODE=default``.
    """
    if explicit:
        mode = explicit.strip().lower()
    else:
        mode = str(getattr(get_settings(), "llm_reasoning_mode", "off") or "off").strip().lower()
    return mode if mode in _REASONING_MODES else "off"


def _agent_max_tokens() -> int | None:
    """Output cap for the agent lane, or ``None`` when unset.

    Measured on the token plans: a 400-token cap still ended with
    ``finish_reason=stop`` (no truncation) and cut a MiniMax turn from 8,489 ms to
    ~6,100 ms; 250 truncated mid-answer on MiniMax. Unset keeps today's unbounded
    behaviour, so this only takes effect when an operator configures it.

    Nothing is configured by default: the admin knob's default is 0 ("no cap"), so
    the answer lane runs unbounded unless an operator chooses the wall-time lever.

    On MiniMax M2.x a configured cap covers the inline `` thinking`` deliberation as
    well as the answer (the provider cannot disable thinking, and the deliberation
    is returned inside ``content``), so a value sized for the answer alone cuts the
    answer mid-word. Such a turn is completed by the answer-completion guard above
    instead of shipping the cut — at the cost of one extra model call, which is the
    second reason the shipped default is no cap.
    """
    raw = getattr(get_settings(), "llm_agent_max_tokens", 0) or 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _minimax_chat(
    model: str,
    *,
    temperature: float,
    max_retries: int = 0,
    api_key: str | None = None,
    max_tokens: int | None = None,
):
    """OpenAI-compatible MiniMax client from settings. Shared construction so
    model / base_url / timeout cannot drift between build_deps and the extractor.

    ``max_retries`` defaults to 0: the agent loop handles 429 explicitly via
    ``_llm_call_with_retry`` (one backoff retry, then LLMThrottled → static
    degradation reply). The openai library's built-in retry would just waste
    time (3× the timeout) on top of that, so it stays off.

    Reasoning cannot be switched off on this endpoint (measured 2026-09-26 on
    ``api.minimax.io/v1`` with MiniMax-M2.7-highspeed): ``thinking:{type:disabled}``,
    ``enable_thinking:false``, ``reasoning:{enabled:false}``, ``reasoning_effort:none``
    and ``chat_template_kwargs`` all still returned 120–220 reasoning tokens, and
    decode stayed ~40–60 tok/s. So this builder deliberately sends no reasoning
    field — an unsupported field would risk 4xx on the primary lane for no gain.
    ``max_tokens`` is the only lever that bounds a MiniMax turn.
    """
    s = get_settings()
    resolved_api_key = api_key or s.minimax_api_key
    if not resolved_api_key:
        raise RuntimeError("MINIMAX_API_KEY is required for MiniMax chat")
    chat_class = _reasoning_chat_class()
    kwargs: dict = {}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return chat_class(
        model=model,
        api_key=resolved_api_key,
        base_url=s.minimax_base_url,
        timeout=s.minimax_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="minimax",
        # Streaming must still report token usage (progressive delivery path).
        stream_usage=True,
        **kwargs,
    )


# Vendors known to accept an explicit thinking-disable field on their
# OpenAI-compatible endpoint. Everything else (an operator-supplied custom
# vendor) gets no reasoning field at all: an unknown vendor can reject an
# undocumented request field and would 4xx the whole lane, so the change stays
# opt-in per known host instead of global.
_THINKING_DISABLE_HOSTS = ("xiaomimimo",)


def _custom_supports_thinking_disable(base_url: str) -> bool:
    host = (base_url or "").split("//", 1)[-1].split("/", 1)[0].lower()
    return any(marker in host for marker in _THINKING_DISABLE_HOSTS)


def _custom_chat(
    model: str,
    *,
    temperature: float,
    api_key: str,
    base_url: str,
    timeout: int | None = None,
    max_retries: int = 0,
    reasoning_mode: str | None = None,
    max_tokens: int | None = None,
):
    """OpenAI-compatible client for the admin-configured failover provider.

    Everything (endpoint, model id, credential) comes from the settings page
    rather than from code, so pointing this at a different vendor is an operator
    action. ``max_retries=0`` for the same reason as the other builders: the
    agent loop owns retry/failover policy.

    Reasoning: the Xiaomi MiMo token plan honours ``thinking:{type:disabled}``
    (measured 2026-09-26: reasoning tokens 41 → 0, and one 12k-token turn dropped
    6,925 ms → 5,227 ms at equal answer length). MiMo exposes no graded budget, so
    ``low`` is honoured as ``disabled``. Only hosts in
    ``_THINKING_DISABLE_HOSTS`` receive the field; any other custom vendor is
    left untouched.
    """
    if not api_key:
        raise RuntimeError("failover provider API key is required")
    if not base_url:
        raise RuntimeError("failover provider base URL is required")
    if not model:
        raise RuntimeError("failover provider model is required")
    s = get_settings()
    chat_class = _reasoning_chat_class()
    mode = _resolve_reasoning_mode(reasoning_mode)
    kwargs: dict = {}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if mode in {"off", "low"} and _custom_supports_thinking_disable(base_url):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return chat_class(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout or s.custom_llm_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="fallback",
        stream_usage=True,
        **kwargs,
    )


def _openrouter_chat(
    model: str,
    *,
    temperature: float,
    timeout: int | None = None,
    json_mode: bool = False,
    max_retries: int = 0,
    api_key: str | None = None,
    reasoning_mode: str | None = None,
    max_tokens: int | None = None,
):
    """OpenAI-compatible OpenRouter client from settings.

    ``reasoning_mode`` (``off`` | ``low`` | ``default``) maps to OpenRouter's
    documented ``reasoning`` body field. The previous behaviour pinned
    ``effort: high`` on every agent call purely to capture the chain-of-thought
    into the decision trace — the user never sees it, and it multiplied wall time
    on the deepest-reasoning models, so it is no longer forced.
    """
    s = get_settings()
    resolved_api_key = api_key or s.openrouter_api_key
    if not resolved_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter chat")
    kwargs = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    mode = _resolve_reasoning_mode(reasoning_mode)
    if mode == "off":
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    elif mode == "low":
        kwargs["extra_body"] = {"reasoning": {"effort": "low", "exclude": False}}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    chat_class = _reasoning_chat_class()
    return chat_class(
        model=model,
        api_key=resolved_api_key,
        base_url=s.openrouter_base_url,
        timeout=timeout or s.openrouter_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="openrouter",
        stream_usage=True,
        # Stable system block as an explicit cache prefix (transport metadata
        # only — the prompt text is unchanged). OpenRouter's docs accept the
        # Anthropic-style breakpoint on a content block and translate it to
        # the routed provider's own syntax; automatic-caching providers
        # upstream simply don't need it.
        system_prefix_cache_control={"type": "ephemeral"},
        **kwargs,
    )


def _active_llm_provider(
    settings=None,
    *,
    minimax_enabled: bool | None = None,
    openrouter_enabled: bool | None = None,
    custom_enabled: bool | None = None,
    default_provider: LlmProvider | None = None,
) -> LlmProvider:
    """Return the provider that serves the first attempt of each turn.

    Resolution order: the operator's chosen default when that provider is
    enabled, then any other enabled provider. Quota failover is handled per-call
    in ``_llm_call_with_retry``; this only picks where a turn starts.
    """
    s = settings or get_settings()
    mm_on = getattr(s, "minimax_enable", True) if minimax_enabled is None else minimax_enabled
    or_on = (
        getattr(s, "openrouter_enable", False) if openrouter_enabled is None else openrouter_enabled
    )
    custom_on = (
        getattr(s, "custom_llm_enable", False) if custom_enabled is None else custom_enabled
    )
    enabled = {"minimax": mm_on, "openrouter": or_on, "custom": custom_on}
    preferred = default_provider or getattr(s, "llm_default_provider", "minimax")
    if enabled.get(preferred):
        return preferred
    for name in ("minimax", "openrouter", "custom"):
        if enabled[name]:
            return name
    raise RuntimeError(
        "No LLM provider enabled: enable MiniMax, OpenRouter, or the custom provider"
    )


def _chat_for_role(
    role: ModelRole,
    *,
    temperature: float,
    json_mode: bool = False,
    minimax_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    minimax_enabled: bool | None = None,
    openrouter_enabled: bool | None = None,
    custom_enabled: bool | None = None,
    custom_config=None,
    default_provider: LlmProvider | None = None,
    openrouter_agent_model: str | None = None,
    openrouter_extractor_model: str | None = None,
    openrouter_digest_model: str | None = None,
    reasoning_mode: str | None = None,
    max_tokens: int | None = None,
):
    """Build the OpenAI-compatible chat client for an agent/extractor/digest role.

    Returns a plain ``ChatOpenAI`` for the single configured provider. The
    active provider is resolved once by ``_active_llm_provider`` (default first,
    falling back to whichever is enabled). Cross-provider failover is NOT wired
    here: the agent loop owns it per-call via ``_llm_call_with_retry`` with a
    failover chain from ``factories._build_failover_chain``, which keeps these
    clients stateless and safe to cache across turns.

    ``reasoning_mode`` / ``max_tokens`` are the admin-configured latency knobs
    resolved by ``build_cached_clients``. An explicit value wins; otherwise the
    settings-backed default applies (``_resolve_reasoning_mode`` /
    ``_agent_max_tokens``). ``max_tokens=0`` means "no cap".
    """
    s = get_settings()
    provider = _active_llm_provider(
        s,
        minimax_enabled=minimax_enabled,
        openrouter_enabled=openrouter_enabled,
        custom_enabled=custom_enabled,
        default_provider=default_provider,
    )
    # The output cap and reasoning mode apply to the answer lane only: the
    # extractor/digest roles produce bounded structured payloads already, and
    # capping them would risk truncating JSON. An explicit caller value (the
    # admin-managed settings resolved by build_cached_clients) wins over the
    # settings-backed default.
    if role == "agent":
        resolved_cap = max_tokens if max_tokens is not None else _agent_max_tokens()
        agent_limits = {"max_tokens": resolved_cap}
        agent_reasoning = reasoning_mode or _resolve_reasoning_mode()
    else:
        agent_limits = {}
        agent_reasoning = "default"

    if provider == "custom":
        if custom_config is None or not custom_config.usable:
            raise RuntimeError("custom LLM provider selected but not fully configured")
        model = custom_config.agent_model
        return _custom_chat(
            model,
            temperature=temperature,
            api_key=custom_config.api_key,
            base_url=custom_config.base_url,
            reasoning_mode=agent_reasoning,
            **agent_limits,
        )

    if provider == "openrouter":
        resolved_openrouter_key = openrouter_api_key or s.openrouter_api_key
        model = {
            "agent": openrouter_agent_model or s.openrouter_agent_model,
            "extractor": openrouter_extractor_model or s.openrouter_extractor_model,
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
            reasoning_mode=agent_reasoning,
            **agent_limits,
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
    model = s.minimax_agent_model if role == "agent" else s.minimax_extractor_model
    return _minimax_chat(
        model,
        temperature=temperature,
        api_key=resolved_minimax_key,
        **agent_limits,
    )
