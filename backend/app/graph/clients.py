"""MiniMax/OpenRouter agent + digest factories, and the tool-calling loop.

Heavy SDKs (google-genai, langchain-openai / langchain-core) are imported LAZILY inside
methods so importing this module stays cheap and free of optional-dependency failures at
import time. Tool schemas + dispatch live in ``schemas.py``. Every concern that is not
the generation loop itself now lives beside its single owner: the embedding transports
and ``build_embedder`` in ``embedders.py``, the output-cap answer surgery in
``answer_repair.py``, the provider chat-model constructors in ``providers.py``, and
the former inline helper families in ``reasoning_compat.py`` (reasoning-field wire
compatibility), ``llm_observability.py`` (Redis observability counters),
``prefetch.py`` (routed pre-lookup heuristics), ``provider_failover.py``
(retry/quota failover) and ``grounding.py`` (reply grounding + active-job authority
rendering).

The moved names are re-exported here (``X as X``), so ``from app.graph.clients import
build_embedder`` / ``_chat_for_role`` and friends keep resolving. Callers that
monkeypatch must target the owning module: ``providers.get_settings`` /
``embedders.get_settings`` now back the constructors, and ``factories.py`` binds its
own imports of the provider builders.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import NamedTuple

from app.core.config import get_settings
from app.graph.answer_repair import (
    _CUT_ANSWER_CONTINUE_INSTRUCTION,
    _MAX_ANSWER_CONTINUATIONS,
    _answer_was_cut,
    _drop_dangling_tail,
    _join_answer_parts,
    _record_answer_continuation,
    _should_continue_cut_answer,
)
from app.graph.embedders import GeminiEmbedder as GeminiEmbedder
from app.graph.embedders import OpenRouterEmbedder as OpenRouterEmbedder
from app.graph.embedders import build_embedder as build_embedder
from app.graph.grounding import (
    LANE_UNAVAILABLE_REPLY,
    VACANCY_LOOKUP_UNAVAILABLE_REPLY,
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
from app.graph.providers import _active_llm_provider as _active_llm_provider
from app.graph.providers import _agent_max_tokens as _agent_max_tokens
from app.graph.providers import _chat_for_role as _chat_for_role
from app.graph.providers import _custom_chat as _custom_chat
from app.graph.providers import _minimax_chat as _minimax_chat
from app.graph.providers import _openrouter_chat as _openrouter_chat
from app.graph.providers import _resolve_reasoning_mode as _resolve_reasoning_mode
from app.graph.reasoning_compat import _extract_returned_reasoning
from app.graph.think_strip import extract_text_tool_calls, strip_provider_artifacts
from app.graph.schemas import _dispatch_tool
from app.graph.usage import record_token_usage as _record_token_usage

logger = logging.getLogger(__name__)


class _ContinueTurn:
    """Marker: a phase produced no reply, so the turn keeps going."""


_CONTINUE_TURN = _ContinueTurn()

# Per-turn metric keys seeded up front so the generation loop can assign
# instead of re-checking membership on every round.
_TURN_METRIC_KEYS = (
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
)


def _init_turn_metrics(metrics: dict | None) -> None:
    """Seed the turn's metric keys; a ``None`` sink is left alone."""
    if metrics is None:
        return
    for key in _TURN_METRIC_KEYS:
        metrics.setdefault(key, 0)
    metrics.setdefault("llm_call_ms", [])


class _RoundResult(NamedTuple):
    """One model round: the response plus the timing splits it produced."""

    message: object
    backoff_ms: int
    queue_ms: int
    model_ms: int
    total_ms: int


class _AgentTurn:
    """Mutable state of one ``MiniMaxAgent.agent`` call.

    One field per local the single ``agent`` body used to carry, so the phases
    (``_prefetch_routes`` → ``_run_generation_round`` → ``_finalize_answer``)
    read exactly the state the monolith did: the split is a move, not a
    rewrite. The three helpers at the bottom are the closures the monolith
    defined inline, with the same bodies.
    """

    __slots__ = (
        "user_text",
        "system",
        "retrieval",
        "embedder",
        "allowed_tools",
        "resolved_tool_registry",
        "make_retrieval",
        "metrics",
        "required_tool",
        "required_tool_args",
        "forced_project_slug",
        "conversation_scope",
        "on_delta",
        "on_evidence",
        "trace_sink",
        "active_llm",
        "schemas",
        "messages",
        "tool_results",
        "contact_evidence",
        "effective_query",
        "prefetch_hit",
        "faq_detail_features_hit",
        "required_tool_called",
        "authority_tool_dispatched",
        "iterations_remaining",
        "empty_retry_available",
        "retrying_empty_generation",
        "answer_parts",
        "answer_continuations",
        "continuing_answer",
        "last_round_cut",
    )

    def __init__(
        self,
        *,
        user_text: str,
        system: str,
        retrieval,
        embedder,
        allowed_tools,
        resolved_tool_registry,
        make_retrieval,
        metrics: dict | None,
        required_tool: str | None,
        required_tool_args: dict | None,
        forced_project_slug: str | None,
        conversation_scope: str = "",
        on_delta,
        on_evidence,
        trace_sink,
        active_llm,
        schemas,
        messages,
        effective_query: str,
        max_iters: int,
        retry_empty_generation: bool,
    ) -> None:
        self.user_text = user_text
        self.system = system
        self.retrieval = retrieval
        self.embedder = embedder
        self.allowed_tools = allowed_tools
        self.resolved_tool_registry = resolved_tool_registry
        self.make_retrieval = make_retrieval
        self.metrics = metrics
        self.required_tool = required_tool
        self.required_tool_args = required_tool_args
        self.forced_project_slug = forced_project_slug
        # Server-side conversation identity (see lanes._agent_turn). Injected
        # into tool args at dispatch so per-conversation tools never trust a
        # model-supplied id.
        self.conversation_scope = conversation_scope
        self.on_delta = on_delta
        self.on_evidence = on_evidence
        self.trace_sink = trace_sink
        self.active_llm = active_llm
        self.schemas = schemas
        self.messages = messages
        self.effective_query = effective_query
        self.iterations_remaining = max_iters
        self.empty_retry_available = retry_empty_generation
        # Captured for post-generation grounding cross-check.
        self.tool_results: list[str] = []
        # Everything the model was shown before it wrote the reply: the system
        # prompt (persona + admin API guide) and the candidate's own message
        # (history included). The contact guard treats a phone number or e-mail
        # outside this text as an invention.
        self.contact_evidence = f"{system}\n{user_text}"
        # Set by the route branches below; seeded so the post-generation
        # prefetched-tools guard can read them unconditionally.
        self.prefetch_hit = False
        self.faq_detail_features_hit = False
        self.required_tool_called = False
        self.authority_tool_dispatched = False
        self.retrying_empty_generation = False
        # Answer rounds of this turn (see the answer-completion guard in
        # answer_repair): normally one, more when the provider cut an answer
        # at its output cap.
        self.answer_parts: list[str] = []
        self.answer_continuations = 0
        self.continuing_answer = False
        self.last_round_cut = False

    def scoped_args(self, name: str, args: dict) -> dict:
        """Force the turn's project focus onto a model-supplied tool call."""
        scoped = _scope_project_tool_args(name, args, self.forced_project_slug)
        if self.conversation_scope:
            scoped = {**scoped, "_conversation_scope": self.conversation_scope}
        return scoped

    async def publish_evidence(self) -> None:
        """Hand the accumulated tool evidence to the progressive sender.

        Called after every ``tool_results`` append (prefetch and dispatched
        rounds alike): a bubble streamed mid-generation must pass the same
        job-id/entity grounding cross-check as the full reply, so it needs
        the evidence the model had actually seen when that text was produced.
        A snapshot copy is passed so a later append cannot mutate it.
        """
        if self.on_evidence is not None:
            await self.on_evidence(list(self.tool_results))

    async def dispatch_one(self, tc: dict) -> str:
        """Run one tool call, on an isolated session when one is wired."""
        name = tc.get("name", "")
        raw_args = (
            dict(self.required_tool_args)
            if name == self.required_tool and self.required_tool_args is not None
            else tc.get("args", {})
        )
        if self.forced_project_slug and name in {
            "list_active_projects",
            "recommend_projects",
            "recommend_jobs",
            "search_bus_timetable",
        }:
            return "Công cụ khám phá nhiều dự án không khả dụng khi cuộc trò chuyện đang tập trung vào một dự án."
        args = self.scoped_args(name, raw_args)
        metrics = self.metrics
        tool_call_t0 = time.monotonic()
        try:
            if self.make_retrieval is not None:
                try:
                    async with self.make_retrieval() as fresh_retrieval:
                        return await _dispatch_tool(
                            fresh_retrieval,
                            self.embedder,
                            name,
                            args,
                            metrics=metrics,
                            resolved_registry=self.resolved_tool_registry,
                        )
                except Exception:  # noqa: BLE001 — session setup failed → shared
                    logger.warning(
                        "isolated retrieval for tool %s failed, using shared",
                        name,
                        exc_info=True,
                    )
            return await _dispatch_tool(
                self.retrieval,
                self.embedder,
                name,
                args,
                metrics=metrics,
                resolved_registry=self.resolved_tool_registry,
            )
        finally:
            if metrics is not None:
                breakdown = metrics.setdefault("tool_breakdown", {})
                breakdown[name] = breakdown.get(name, 0) + int(
                    (time.monotonic() - tool_call_t0) * 1000
                )


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
        conversation_scope: str = "",
        retry_empty_generation: bool = False,
        on_delta=None,
        on_evidence=None,
        trace_sink=None,
    ) -> str:
        """Run the tool-calling turn: prefetch, generate, finalize.

        Orchestrator only. It picks the model, seeds the turn state, and runs
        the three phases in order; a phase that produced a candidate-facing
        reply (``compare_income``'s grounded authority text, or any final
        answer) short-circuits the ones after it.
        """
        from app.graph.schemas import filter_tool_schemas
        from langchain_core.messages import SystemMessage

        active_llm = self.fast_llm if (use_fast and self.fast_llm is not None) else self.llm
        if trace_sink is not None:
            trace_sink.record_decision("model_selected", "fast" if use_fast else "primary")
        if trace_sink is not None and required_tool is not None:
            trace_sink.record_decision("required_tool_selected", required_tool)
        schemas = filter_tool_schemas(allowed_tools, resolved_registry=resolved_tool_registry)
        _init_turn_metrics(metrics)
        turn = _AgentTurn(
            user_text=user_text,
            system=system,
            retrieval=retrieval,
            embedder=embedder,
            allowed_tools=allowed_tools,
            resolved_tool_registry=resolved_tool_registry,
            make_retrieval=make_retrieval,
            metrics=metrics,
            required_tool=required_tool,
            required_tool_args=required_tool_args,
            forced_project_slug=forced_project_slug,
            conversation_scope=conversation_scope,
            on_delta=on_delta,
            on_evidence=on_evidence,
            trace_sink=trace_sink,
            active_llm=active_llm,
            schemas=schemas,
            messages=[SystemMessage(content=system)],
            effective_query=lookup_query or user_text,
            max_iters=self.max_iters,
            retry_empty_generation=retry_empty_generation,
        )

        early = await self._prefetch_routes(turn)
        if early is not _CONTINUE_TURN:
            return early
        early = await self._run_generation_round(turn)
        if early is not _CONTINUE_TURN:
            return early
        return await self._finalize_answer(turn)

    async def _prefetch_routes(self, turn: _AgentTurn) -> str | _ContinueTurn:
        """Run the routed pre-lookups, then bind the tools generation may use.

        Each lane short-circuits generation when its authority tool already ran
        and hit: the model never re-searches data the turn already holds. Only
        ``compare_income`` answers outright (its payload renders its own
        grounded text), so it is the one branch that returns a reply here.
        """
        from langchain_core.messages import SystemMessage

        allowed_tools = turn.allowed_tools
        effective_query = turn.effective_query
        forced_project_slug = turn.forced_project_slug
        make_retrieval = turn.make_retrieval
        metrics = turn.metrics
        messages = turn.messages
        required_tool = turn.required_tool
        required_tool_args = turn.required_tool_args
        resolved_tool_registry = turn.resolved_tool_registry
        retrieval = turn.retrieval
        embedder = turn.embedder
        trace_sink = turn.trace_sink

        knowledge_lookup_route = allowed_tools == ("search_knowledge",)
        timetable_route = allowed_tools == ("search_bus_timetable",)
        income_compare_route = allowed_tools == ("compare_income",)
        faq_detail_route = allowed_tools == (
            "get_product_features",
            "search_knowledge",
        )
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
                    turn.scoped_args("search_knowledge", {"query": effective_query}),
                    metrics=metrics,
                    resolved_registry=resolved_tool_registry,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Contact knowledge prefetch failed", exc_info=True)
            else:
                turn.tool_results.append(str(prefetched))
                await turn.publish_evidence()
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
            prefetched, turn.prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "search_knowledge",
                turn.scoped_args("search_knowledge", {"query": effective_query}),
                metrics,
                resolved_tool_registry,
                dispatch=_dispatch_tool,
            )
            turn.tool_results.append(str(prefetched))
            await turn.publish_evidence()
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
            turn.schemas = []
        elif timetable_route:
            if trace_sink is not None:
                trace_sink.record_tool_selection("search_bus_timetable", selected_by="prefetch")
            prefetched, turn.prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "search_bus_timetable",
                turn.scoped_args(
                    "search_bus_timetable",
                    {"company": "", "question": effective_query},
                ),
                metrics,
                resolved_tool_registry,
                dispatch=_dispatch_tool,
            )
            if turn.prefetch_hit:
                turn.tool_results.append(str(prefetched))
                await turn.publish_evidence()
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
                turn.schemas = []
        elif income_compare_route:
            if trace_sink is not None:
                trace_sink.record_tool_selection("compare_income", selected_by="prefetch")
            prefetched, turn.prefetch_hit = await _prefetch_tool(
                retrieval,
                embedder,
                "compare_income",
                dict(required_tool_args or {}),
                metrics,
                resolved_tool_registry,
                dispatch=_dispatch_tool,
            )
            if turn.prefetch_hit:
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
                turn.prefetch_hit = False
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
                knowledge_args = turn.scoped_args(
                    "search_knowledge", {"query": effective_query}
                )
                features_args = turn.scoped_args(
                    "get_product_features", {"project_slug": focused_slug}
                )
                if make_retrieval is not None:
                    outcomes = await asyncio.gather(
                        _bounded_prefetch("search_knowledge", knowledge_args),
                        _bounded_prefetch("get_product_features", features_args),
                    )
                    (prefetched, turn.prefetch_hit), (features, features_hit) = outcomes
                else:
                    # Web-chat builds dependencies around one request-scoped
                    # AsyncSession. Keep these calls sequential when no isolated
                    # retrieval factory exists; AsyncSession is not concurrency-safe.
                    prefetched, turn.prefetch_hit = await _prefetch_tool(
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
                prefetched, turn.prefetch_hit = await _prefetch_tool(
                    retrieval,
                    embedder,
                    "search_knowledge",
                    turn.scoped_args("search_knowledge", {"query": effective_query}),
                    metrics,
                    resolved_tool_registry,
                    dispatch=_dispatch_tool,
                )
                features = None
                features_hit = False
            if turn.prefetch_hit:
                turn.tool_results.append(str(prefetched))
                await turn.publish_evidence()
                if features_hit:
                    turn.tool_results.append(str(features))
                    await turn.publish_evidence()
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
                turn.schemas = []
            turn.faq_detail_features_hit = features_hit
        # Each prefetch route (knowledge_lookup_route / timetable_route /
        # faq_detail_route) may eagerly run its authority tool above and then set
        # schemas=[] to skip the model-driven tool-dispatch loop. The
        # post-generation guard in _finalize_answer (`if required_tool and not
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
        if knowledge_lookup_route and turn.prefetch_hit:
            prefetched_tools.add("search_knowledge")
        if timetable_route and turn.prefetch_hit:
            prefetched_tools.add("search_bus_timetable")
        if income_compare_route and turn.prefetch_hit:
            prefetched_tools.add("compare_income")
        if faq_detail_route and turn.prefetch_hit:
            prefetched_tools.add("search_knowledge")
            # Focused faq_detail turns also prefetch get_product_features in
            # parallel; record it so required_tool guards recognize it as run.
            if turn.faq_detail_features_hit:
                prefetched_tools.add("get_product_features")
        turn.required_tool_called = bool(
            required_tool and required_tool in prefetched_tools
        )
        turn.authority_tool_dispatched = bool(
            required_tool == "list_active_jobs" and turn.required_tool_called
        )
        return _CONTINUE_TURN
    async def _run_generation_round(self, turn: _AgentTurn) -> str | _ContinueTurn:
        """Loop model rounds and tool dispatches until the turn answers.

        Returns the candidate-facing reply as soon as one is produced (a
        recovery round, a plain final answer, or a required tool's own grounded
        text), or ``_CONTINUE_TURN`` when the round budget ran out first — the
        caller then decides what an unanswered turn ships.
        """
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        active_llm = turn.active_llm
        metrics = turn.metrics
        messages = turn.messages
        required_tool = turn.required_tool
        required_tool_args = turn.required_tool_args
        schemas = turn.schemas
        trace_sink = turn.trace_sink

        if schemas and hasattr(active_llm, "bind_tools"):
            bound = (
                active_llm.bind_tools(schemas, tool_choice=required_tool)
                if required_tool
                else active_llm.bind_tools(schemas)
            )
        else:
            bound = active_llm

        messages.append(HumanMessage(content=turn.user_text))
        while turn.iterations_remaining > 0:
            turn.iterations_remaining -= 1
            if metrics is not None:
                metrics["llm_calls"] = metrics.get("llm_calls", 0) + 1
            # This iteration is a recovery attempt only if the previous round
            # asked for one. Recovery is deliberately tool-free: the reply came
            # back empty *because* the tool round consumed the answer budget, so
            # re-asking without tools is what produces prose.
            was_empty_retry = turn.retrying_empty_generation
            # A recovery round and an answer-continuation round are both
            # tool-free: a cut answer is continued as prose, never by re-entering
            # tool dispatch.
            tool_free_round = was_empty_retry or turn.continuing_answer
            invocation_llm = active_llm if tool_free_round else bound

            invoked = await self._invoke_round(
                turn,
                invocation_llm=invocation_llm,
                tool_free_round=tool_free_round,
            )
            if invoked is None:
                # The empty-generation recovery failed; the turn ships nothing
                # and the runner's fallback takes over.
                return ""
            ai = invoked.message
            backoff_ms = invoked.backoff_ms
            if metrics is not None:
                metrics["llm_invoke_ms"] = metrics.get("llm_invoke_ms", 0) + invoked.total_ms
                metrics["llm_queue_ms"] = metrics.get("llm_queue_ms", 0) + invoked.queue_ms
                # Exclude the 429 backoff sleep from model inference so the split
                # stays clean: llm_model_ms = actual ainvoke time only. The
                # backoff is surfaced separately so the dashboard can attribute it.
                metrics["llm_model_ms"] = metrics.get("llm_model_ms", 0) + (
                    invoked.model_ms - backoff_ms
                )
                if backoff_ms > 0:
                    metrics["llm_backoff_ms"] = metrics.get("llm_backoff_ms", 0) + backoff_ms
                metrics["llm_call_ms"].append(invoked.model_ms - backoff_ms)
            # Live Redis counter tracks the full LLM path (queue + model) — the
            # right number for the "is the LLM path slow right now?" live tile.
            await _record_llm_latency(invoked.total_ms)
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
            logger.info("llm_invoke", extra={"llm_latency_ms": invoked.total_ms})
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None)
            turn.last_round_cut = _answer_was_cut(ai)
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
                turn.answer_parts.append(visible_round)
                if _should_continue_cut_answer(ai, visible_round, turn.answer_continuations):
                    turn.answer_continuations += 1
                    turn.continuing_answer = True
                    messages.append(SystemMessage(content=_CUT_ANSWER_CONTINUE_INSTRUCTION))
                    _record_answer_continuation(metrics, turn.answer_continuations)
                    continue
                answer = _join_answer_parts(turn.answer_parts)
                if _answer_was_cut(ai):
                    # Still cut after the continuation budget: drop the dangling
                    # fragment instead of a mid-word tail.
                    answer = _drop_dangling_tail(answer)
                return _ground_reply(
                    answer,
                    turn.tool_results,
                    allowed_text=turn.contact_evidence,
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
                    text_outs = [await turn.dispatch_one(call) for call in text_calls]
                    for call, out in zip(text_calls, text_outs):
                        turn.tool_results.append(str(out))
                        await turn.publish_evidence()
                        if call["name"] == required_tool:
                            turn.required_tool_called = True
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
                    and turn.empty_retry_available
                    and (required_tool is None or turn.required_tool_called)
                ):
                    turn.empty_retry_available = False
                    turn.retrying_empty_generation = True
                    turn.iterations_remaining += 1
                    messages.pop()
                    if metrics is not None:
                        metrics["generation_retry_count"] = 1
                        metrics["generation_retry_reason"] = "empty_after_clean"
                    continue
                if required_tool and not turn.required_tool_called:
                    logger.warning("required LLM tool was not called: %s", required_tool)
                    return await self.direct(
                        turn.user_text,
                        system=(
                            "Bạn là tư vấn viên tuyển dụng. Dữ liệu tuyển dụng bắt buộc chưa được "
                            "truy xuất thành công. Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa "
                            "thể kiểm tra, không xác nhận có việc và không bịa dữ liệu."
                        ),
                        metrics=metrics,
                        trace_sink=trace_sink,
                    )
                turn.answer_parts.append(visible_round)
                if _should_continue_cut_answer(ai, visible_round, turn.answer_continuations):
                    turn.answer_continuations += 1
                    turn.continuing_answer = True
                    messages.append(SystemMessage(content=_CUT_ANSWER_CONTINUE_INSTRUCTION))
                    _record_answer_continuation(metrics, turn.answer_continuations)
                    logger.warning(
                        "answer cut by the provider output cap; continuing %d/%d",
                        turn.answer_continuations,
                        _MAX_ANSWER_CONTINUATIONS,
                    )
                    continue
                # Active-job authority turns fail closed to the tool-rendered
                # safe reply. This removes the former third LLM rewrite while
                # avoiding partial regex validation of titles, locations,
                # vacancy counts, and salary formats. Other tools retain the
                # sanitize-only ID/entity grounding path.
                final_reply = _join_answer_parts(turn.answer_parts)
                if _answer_was_cut(ai):
                    # The provider stopped at the cap again: drop the dangling
                    # fragment so the candidate never reads a mid-word tail.
                    final_reply = _drop_dangling_tail(final_reply)
                if turn.authority_tool_dispatched:
                    final_reply = _ground_active_job_reply(final_reply, turn.tool_results)
                return _ground_reply(
                    final_reply,
                    turn.tool_results,
                    allowed_text=turn.contact_evidence,
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
            if len(calls) > 1 and turn.make_retrieval is not None:
                tool_sem = asyncio.Semaphore(get_settings().parallel_tool_max_concurrency)

                async def _bounded(tc: dict) -> str:
                    async with tool_sem:
                        return await turn.dispatch_one(tc)

                outs = await asyncio.gather(*[_bounded(tc) for tc in calls])
            else:
                outs = [await turn.dispatch_one(tc) for tc in calls]
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
                    turn.required_tool_called = True
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
                            turn.user_text,
                            system=(
                                "Bạn là tư vấn viên tuyển dụng. Kết quả kiểm tra tuyển dụng không "
                                "hợp lệ. Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể xác minh, "
                                "không xác nhận có việc và không bịa dữ liệu."
                            ),
                            metrics=metrics,
                            trace_sink=trace_sink,
                        )
                if tool_name == "list_active_jobs":
                    turn.authority_tool_dispatched = True
                turn.tool_results.append(str(out))
                messages.append(
                    ToolMessage(
                        content=str(out),
                        tool_call_id=tc.get("id") or f"call_{idx}_{tc.get('name', 'tool')}",
                    )
                )
            # One publish per dispatch round: the next model call is the one that
            # can stream a bubble, and by then every result above is in hand.
            await turn.publish_evidence()
            if turn.required_tool_called and schemas and hasattr(active_llm, "bind_tools"):
                # Require the authority tool only on the first model round. After
                # evidence is present, allow the model to produce its final turn.
                bound = active_llm.bind_tools(schemas)
        return _CONTINUE_TURN

    async def _invoke_round(
        self,
        turn: _AgentTurn,
        *,
        invocation_llm,
        tool_free_round: bool,
    ) -> _RoundResult | None:
        """One model call, under the deployment-wide Redis concurrency cap.

        Returns ``None`` when an empty-generation recovery round failed, which
        hands the turn back to the runner's fallback rather than raising. Every
        other provider failure (including saturation) propagates unchanged.
        """
        from app.graph.llm_semaphore import LLMThrottled, get_llm_semaphore

        metrics = turn.metrics
        schemas = turn.schemas
        # Split the LLM path into semaphore-queue wait vs. model inference.
        # Previously a single timer covered both, so a 34s "LLM" p95 was
        # ambiguous between a slow model and self-inflicted throttle wait.
        sem_t0 = time.monotonic()
        try:
            # Re-acquired every round on purpose. The deployment-wide Redis
            # cap is the only bound that survives a tool round, so a local
            # name resolved once at entry — or rebound by the parallel tool
            # dispatcher — would silently drop every later round of
            # this turn out of the cap (and out of the fail-fast that turns
            # saturation into a clean suppressed turn).
            async with get_llm_semaphore():
                sem_wait_ms = int((time.monotonic() - sem_t0) * 1000)
                model_t0 = time.monotonic()
                # The failover client must carry the same tool bindings as
                # the primary, or a mid-loop switch would lose the tools the
                # conversation already depends on.
                _fallback_bounds = [
                    _bind_like(client, schemas, bound_primary=not tool_free_round)
                    for client in self.fallback_llms
                ]
                if turn.on_delta is not None:
                    # Progressive delivery: forward answer text as it is
                    # produced so the first complete bubble can be sent
                    # before the generation finishes. A tool-request round
                    # emits no visible text, so nothing is sent for it.
                    ai, backoff_ms = await _llm_call_streaming_with_retry(
                        invocation_llm,
                        turn.messages,
                        on_delta=turn.on_delta,
                        metrics=metrics,
                        fallback_bounds=_fallback_bounds,
                    )
                else:
                    ai, backoff_ms = await _llm_call_with_retry(
                        invocation_llm,
                        turn.messages,
                        metrics=metrics,
                        fallback_bounds=_fallback_bounds,
                    )
                model_ms = int((time.monotonic() - model_t0) * 1000)
        except LLMThrottled:
            if turn.retrying_empty_generation:
                if metrics is not None:
                    metrics["generation_retry_failure"] = "throttled"
                return None
            raise
        except Exception as exc:
            if turn.retrying_empty_generation:
                # Recovery is best-effort: a failed retry hands the turn back
                # to the runner's fallback instead of a provider error.
                if metrics is not None:
                    metrics["generation_retry_failure"] = type(exc).__name__
                logger.warning(
                    "empty-generation retry failed error_type=%s",
                    type(exc).__name__,
                )
                return None
            # Track provider 429s for observability (Phase 0 metric).
            if _is_429(exc):
                await _record_llm_429()
                logger.error("llm_429", exc_info=True)
            raise
        return _RoundResult(
            message=ai,
            backoff_ms=backoff_ms,
            queue_ms=sem_wait_ms,
            model_ms=model_ms,
            total_ms=int((time.monotonic() - sem_t0) * 1000),
        )

    async def _finalize_answer(self, turn: _AgentTurn) -> str:
        """Decide what a turn that exhausted its round budget ships.

        Either the required authority tool never ran (the model ignored it), or
        every round went to tool calls and no prose was ever generated.
        """
        required_tool = turn.required_tool
        metrics = turn.metrics
        trace_sink = turn.trace_sink
        if required_tool and not turn.required_tool_called:
            return await self.direct(
                turn.user_text,
                system=(
                    "Bạn là tư vấn viên tuyển dụng. Không có dữ liệu tuyển dụng đã xác minh cho "
                    "lượt này. Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể kiểm tra, không "
                    "xác nhận có việc và không bịa dữ liệu."
                ),
                metrics=metrics,
                trace_sink=trace_sink,
            )
        if turn.answer_parts:
            # A continued answer outranks the last message: exhaustion after a
            # cut-answer continuation must never ship the instruction text.
            final = _join_answer_parts(turn.answer_parts)
            if turn.last_round_cut:
                final = _drop_dangling_tail(final)
        else:
            # The loop spent every round on tool calls and never produced a text
            # answer. ``messages[-1].content`` is the raw ToolMessage payload
            # here (an ACTIVE_JOB_LOOKUP_JSON dump or a KB chunk) and must never
            # reach a candidate: the grounding cross-check below waves it through
            # precisely because the ids inside tool output are by definition in
            # the surfaced set. The lane's neutral unavailable line is the only
            # honest reply, and the trace records the degradation.
            if trace_sink is not None:
                trace_sink.record_decision("degradation_reason", "tool_loop_exhausted")
            if metrics is not None:
                metrics["tool_loop_exhausted"] = True
            final = (
                VACANCY_LOOKUP_UNAVAILABLE_REPLY
                if required_tool == "list_active_jobs" or turn.authority_tool_dispatched
                else LANE_UNAVAILABLE_REPLY
            )
        if turn.authority_tool_dispatched:
            final = _ground_active_job_reply(str(final or ""), turn.tool_results)
        # Apply the same deterministic authority boundary on loop exhaustion;
        # no third LLM rewrite call is needed.
        return _ground_reply(
            final,
            turn.tool_results,
            allowed_text=turn.contact_evidence,
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
        ``agent`` (see ``answer_repair``): this lane produces
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
