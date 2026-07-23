"""The bot-turn pipeline (mirrors the LangGraph topology 1:1; node-named functions).

    load_conversation_state -> typing -> agent
      agent (error) -> error_reply
      agent (ok)    -> fast_safety_filter -> needs_llm_safety?
                         no  -> combine_for_presend
                         yes -> llm_safety_check -> safe_to_send?
                                   yes -> combine_for_presend
                                   no -> retry_rewrite? (attempt<1) -> agent | combine_for_presend
      combine_for_presend -> pre_send_guard -> ownership_ok?
                                yes -> send_message -> log_sent
                                no -> log_suppressed

LLM/embedder/Zalo/DB are injected via GraphDeps (defined in ``app.graph.types``), so
the safety/ownership/suppress branches are unit-testable with fakes (no API keys needed).
Live parity (acceptance #4 grounding / #5 off-topic via real MiniMax) is exercised through
graph/factories.py + graph/clients.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import suppress
from inspect import Parameter, iscoroutinefunction, signature
from typing import Any

from app.conversation_messaging.domain.delivery import DeliveryState
from app.core.config import get_settings
from app.graph.decision_trace import DecisionTraceBuilder
from app.graph.ports import DeliveryResultPort, DirectMessageSenderPort, SendOutcome
from app.shared.application.outbound import (
    AMBIGUOUS_SEND_CLASSES,
    OutboundTelemetry,
    is_ambiguous_send,
)
from app.graph.llm_semaphore import LLMThrottled
from app.graph.prompt_context import build_agent_user_text
from app.graph.direct_context import (
    build_direct_system,
    build_direct_user_text,
)
from app.graph.prompts import ERROR_REPLY
from app.graph.router import (
    detect_recency_sort_intent,
    detect_salary_sort_intent,
    is_vacancy_lookup,
    route_turn,
    routing_instruction,
    should_use_fast_model,
)
from app.graph.schemas import ROUTE_CONFIDENCE_FLOOR
from app.graph.types import BotRunState, GraphDeps, TurnOutcome, _now

logger = logging.getLogger(__name__)
RECENT_HISTORY_LIMIT = 16
DIRECT_HISTORY_TOKEN_BUDGET = 12_000
OA_PROFILE_LOOKUP_TIMEOUT_SECONDS = 2.0
VACANCY_LOOKUP_UNAVAILABLE_REPLY = (
    "Hiện tôi chưa thể kiểm tra thông tin tuyển dụng. Bạn vui lòng thử lại sau nhé."
)


def _delivery_status_for_send_error(
    error_class: str | None,
    *,
    ok: bool,
    send_unknown: Any,
):
    return send_unknown if is_ambiguous_send(error_class, ok=ok) else None


def _delivery_statuses(deps: GraphDeps):
    if deps.delivery_statuses is not None:
        return deps.delivery_statuses

    class _NeutralDeliveryStatuses:
        suppressed = DeliveryState.SUPPRESSED
        send_unknown = DeliveryState.SEND_UNKNOWN

    return _NeutralDeliveryStatuses()

def _remaining(state: BotRunState) -> float:
    """Seconds left until the propagated turn deadline (``inf`` if unset).

    Epoch-based (stamped by the webhook, carried in the job) so it survives the
    FastAPI→RQ process boundary that ``time.monotonic()`` cannot cross. Tests that
    don't set a deadline get unbounded behaviour (legacy).
    """
    if state.deadline_at_epoch <= 0:
        return float("inf")
    return state.deadline_at_epoch - time.time()


def _zalo_for_conversation(deps: GraphDeps, conv):
    if hasattr(deps.zalo, "for_conversation"):
        return deps.zalo.for_conversation(conv)
    return deps.zalo


def _channel_for_conversation(conv) -> str:
    """Return the persisted delivery channel, never inferring it from a wrapper."""
    return "zalo_oa" if getattr(conv, "zalo_channel", "bot") == "oa" else "zalo_bot"


def _build_outbox_payload(chat_id: str, text: str, quote_message_id: str | None) -> dict:
    """Build the Zalo send payload recorded in the outbox.

    Captures the exact body sent to Zalo so a re-dispatch (from the sweep) can
    reconstruct the call without re-running the turn. ``quote_message_id`` is
    the OA CS-reply field (None on the Bot channel).
    """
    payload: dict = {"chat_id": chat_id, "text": text}
    if quote_message_id:
        payload["quote_message_id"] = quote_message_id
    return payload


async def _dispatch_claimed_message(
    svc,
    zalo: DirectMessageSenderPort,
    conv,
    *,
    message_id: int | None,
    text: str,
    quote_message_id: str | None,
) -> DeliveryResultPort:
    """Send an already-persisted command, retaining fake-port compatibility."""
    dispatch = getattr(svc, "dispatch_outbound_message", None)
    if callable(dispatch) and iscoroutinefunction(dispatch):
        result = await dispatch(message_id=message_id)
        if result is not None:
            return result
        return SendOutcome(
            ok=False,
            error="outbound command was not available for dispatch",
        )
    if quote_message_id:
        return await zalo.send_message(conv.zalo_chat_id, text, quote_message_id=quote_message_id)
    return await zalo.send_message(conv.zalo_chat_id, text)


def _stamp_end_to_end(state: BotRunState, timings: dict | None) -> None:
    """Record candidate-visible latency from webhook receipt through completion."""
    if timings is None or state.received_at_epoch <= 0:
        return
    timings["end_to_end_ms"] = max(0, int(round((time.time() - state.received_at_epoch) * 1000)))


def _stamp_outbound_telemetry(timings: dict | None, send_result) -> None:
    """Persist adapter-neutral metrics when a sender provides them.

    Legacy fakes and non-message send paths intentionally remain valid: absence
    of telemetry is not a delivery failure and simply leaves the additive keys
    out of the historical row.
    """
    telemetry = getattr(send_result, "telemetry", None)
    if timings is not None and isinstance(telemetry, OutboundTelemetry):
        timings.update(telemetry.to_stage_timings())


def _with_optional_trace(callable_obj, kwargs: dict, trace_sink) -> dict:
    """Add the trace sink when the injected agent supports it.

    The graph protocol keeps trace capture additive. Existing installations may
    provide an agent implementation that predates the optional keyword, so the
    runner feature-detects support at the call boundary.
    """
    if trace_sink is None:
        return kwargs
    try:
        parameters = signature(callable_obj).parameters
    except (TypeError, ValueError):
        parameters = {}
    supports_keyword = "trace_sink" in parameters or any(
        parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    if not supports_keyword:
        return kwargs
    return {**kwargs, "trace_sink": trace_sink}


async def _agent_turn(
    state: BotRunState,
    deps: GraphDeps,
    user_text: str,
    *,
    provider: str,
    chat_id: str,
    recent_messages: list[Any],
    timings: dict | None = None,
    trace_sink=None,
    manifest_policy=None,
    project_context=None,
) -> str:
    route = route_turn(user_text)
    focused_project = bool(
        project_context is not None and getattr(project_context, "state", None) == "FOCUSED"
    )
    evidence_query = _vacancy_evidence_query(
        user_text,
        recent_messages,
        focused_project=focused_project,
    )
    vacancy_catalog_required = route.reason == "vacancy_listing" or (
        route.intent == "general" and _recent_vacancy_query(recent_messages) is not None
    )
    vacancy_authority_tool = (
        "list_active_jobs" if vacancy_catalog_required else None
    )
    if manifest_policy is not None and manifest_policy.pack_key != "recruitment":
        allowed_tools = (
            route.tools if route.confidence >= ROUTE_CONFIDENCE_FLOOR else None
        )
        if vacancy_catalog_required:
            allowed_tools = ("list_active_jobs",)
        if allowed_tools is not None:
            allowed_tools = tuple(
                name for name in allowed_tools if name in manifest_policy.tool_registry.names
            )
        if vacancy_authority_tool is not None and not manifest_policy.tool_registry.allows(
            vacancy_authority_tool
        ):
            return await deps.agent.direct(
                user_text,
                **_with_optional_trace(
                    deps.agent.direct,
                    {
                        "system": (
                    "Bạn là tư vấn viên tuyển dụng. Công cụ dữ liệu cần thiết hiện không khả dụng. "
                    "Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể kiểm tra thông tin, không "
                    "khẳng định có việc và không bịa dữ liệu."
                        ),
                        "metrics": timings,
                    },
                    trace_sink,
                ),
            )
        return await run_manifest_composed_agent(
            user_text,
            deps,
            policy=manifest_policy,
            allowed_tools=allowed_tools,
            lookup_query=evidence_query or user_text,
            required_tool="list_active_jobs" if vacancy_catalog_required else None,
            required_tool_args=_vacancy_required_args(user_text) if vacancy_catalog_required else None,
            metrics=timings,
            retry_empty_generation=True,
            trace_sink=trace_sink,
        )

    # System prompt = active persona + master index of active products (best-effort;
    # collapses to AGENT_SYSTEM_PROMPT on any failure so a turn never breaks).
    # Redis-cached (10min TTL, version-bumped on persona/project edits) so a hit
    # is sub-ms; a miss does 2 DB reads (persona + active-product index). Timed
    # separately so the dashboard can attribute it rather than hiding it inside
    # the (post-preamble) total_ms slice.
    from app.graph.context import build_system_prompt

    sys_t0 = time.monotonic()
    system, sys_prompt_hit = await build_system_prompt(
        deps.retrieval,
        provider=provider,
    )
    if project_context is not None:
        if project_context.state == "FOCUSED":
            system += (
                "\n\n=== DỰ ÁN ĐANG ĐƯỢC CHỌN ===\n"
                f"Dự án: {project_context.project_name} "
                f"(slug: {project_context.project_slug}).\n"
                "Mọi tra cứu chi tiết trong lượt này phải giới hạn đúng slug trên. "
                "Không được dùng dữ liệu chi tiết của dự án khác. Câu trả lời cuối cùng "
                "phải do bạn diễn đạt từ bằng chứng tool trả về."
            )
        else:
            system += (
                "\n\n=== CHẾ ĐỘ KHÁM PHÁ ===\n"
                "Ứng viên chưa chọn dự án. Chỉ dùng danh mục dự án và việc làm đang hoạt động "
                "để gợi ý một nhóm nhỏ phù hợp; không tải kiến thức chi tiết của mọi dự án."
            )
    if timings is not None:
        timings["system_prompt_ms"] = int(round((time.monotonic() - sys_t0) * 1000))
        timings["system_prompt_cache_hit"] = sys_prompt_hit

    # Fetch existing lead profile so the agent can see what info is already known
    # and subtly ask for the most important missing fields. Best-effort: DB error
    # simply skips injection (a turn never breaks because of this).
    lead_t0 = time.monotonic()
    lead_profile = ""
    lead_collection_question = ""
    lead_collection_instruction = ""
    if timings is not None:
        timings.setdefault("intent", route.intent)
        timings.setdefault("route_strategy", route.strategy)
        timings.setdefault("route_confidence", round(route.confidence, 2))
    # Hard tool-gate: a confident route constrains which tools the LLM may call.
    # Low-confidence routes fall through to the full toolset (filter_tool_schemas
    # returns the whole registry when allowed is empty/None).
    allowed_tools = route.tools if route.confidence >= ROUTE_CONFIDENCE_FLOOR else None
    if vacancy_catalog_required:
        allowed_tools = ("list_active_jobs",)
    resolved_tool_registry = None
    if manifest_policy is not None:
        # Recruitment retains its proven prompt/routing path, but its bound
        # tools are still the manifest's immutable allowlist.  A low-confidence
        # route therefore cannot restore the full legacy registry.
        resolved_tool_registry = manifest_policy.tool_registry.names
        if allowed_tools is not None:
            allowed_tools = tuple(
                name for name in allowed_tools if name in resolved_tool_registry
            )
    if (
        vacancy_authority_tool is not None
        and resolved_tool_registry is not None
        and vacancy_authority_tool not in resolved_tool_registry
    ):
        return await deps.agent.direct(
            user_text,
            **_with_optional_trace(
                deps.agent.direct,
                {
                    "system": (
                "Bạn là tư vấn viên tuyển dụng. Công cụ dữ liệu cần thiết hiện không khả dụng. "
                "Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể kiểm tra thông tin, không "
                "khẳng định có việc và không bịa dữ liệu."
                    ),
                    "metrics": timings,
                },
                trace_sink,
            ),
        )
    focused_rag = (
        project_context is not None
        and project_context.state == "FOCUSED"
        and project_context.knowledge_mode == "RAG"
    )
    if focused_rag:
        authority_tool = (
            "list_active_jobs" if vacancy_catalog_required else "search_knowledge"
        )
        if resolved_tool_registry is not None and authority_tool not in resolved_tool_registry:
            return await deps.agent.direct(
                user_text,
                **_with_optional_trace(
                    deps.agent.direct,
                    {
                        "system": (
                    "Bạn là tư vấn viên tuyển dụng. Dữ liệu của dự án hiện không thể tra cứu. "
                    "Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa có thông tin đã xác minh, "
                    "không khẳng định có việc và không bịa dữ liệu."
                        ),
                        "metrics": timings,
                    },
                    trace_sink,
                ),
            )
        # Detailed Project answers use only the Project-owned category authority.
        # This also keeps legacy global timetable/project tools out of a focused turn.
        allowed_tools = (authority_tool,)
    # Model tier (Phase 5): low-complexity strategies use the fast model when one
    # is configured. ``should_use_fast_model`` encodes eligibility; the agent no-ops
    # the switch when no fast model was injected (tests / un-configured deployments).
    use_fast = should_use_fast_model(route)
    if timings is not None:
        timings["model_tier"] = "fast" if use_fast else "primary"
    allow_lead_context = (
        manifest_policy is None
        or (
            manifest_policy.pack_key == "recruitment"
            and "candidate_intake" in manifest_policy.capability_ids
        )
    )
    if allow_lead_context:
        try:
            lead_profile, lead_collection_question = await deps.lead.context(
                chat_id, user_text, recent_messages
            )
            if lead_collection_question:
                lead_collection_instruction = deps.lead.instruction(lead_collection_question)
        except Exception:  # noqa: BLE001
            logger.warning(
                "lead profile fetch failed for %s, skipping injection", chat_id, exc_info=True
            )
    if timings is not None:
        # Accumulate because the shared timing dictionary may already include
        # work from earlier reactive-turn stages.
        timings["lead_ms"] = timings.get("lead_ms", 0) + int(
            round((time.monotonic() - lead_t0) * 1000)
        )

    route_hint = (
        routing_instruction(route_turn(_recent_vacancy_query(recent_messages) or ""))
        if vacancy_catalog_required and route.reason != "vacancy_listing"
        else routing_instruction(route)
    )

    contextual_user_text = build_agent_user_text(
        chat_id=chat_id,
        current_user_text=user_text,
        recent_messages=recent_messages,
        lead_profile=lead_profile,
        lead_collection_instruction=lead_collection_instruction,
        route_hint=route_hint,
    )
    # LLM stage timing is captured inside ``MiniMaxAgent.agent`` (clients.py) as
    # the split ``llm_queue_ms`` (semaphore wait) + ``llm_model_ms`` (inference)
    # pair, written directly into the shared ``timings`` dict. No external timer
    # here — wrapping the agent call would double-count the semaphore wait.
    agent_kwargs = {
        "system": system,
        "retrieval": deps.retrieval,
        "embedder": deps.embedder,
        "allowed_tools": allowed_tools,
        "use_fast": use_fast,
        "make_retrieval": deps.make_retrieval,
        "lookup_query": evidence_query or user_text,
        "metrics": timings,
        "retry_empty_generation": True,
    }
    if focused_rag and not vacancy_catalog_required:
        agent_kwargs["forced_project_slug"] = project_context.project_slug
    if vacancy_catalog_required:
        agent_kwargs["required_tool"] = "list_active_jobs"
        required_args = _vacancy_required_args(user_text)
        agent_kwargs["required_tool_args"] = required_args
    elif focused_rag:
        agent_kwargs["required_tool"] = "search_knowledge"
        agent_kwargs["required_tool_args"] = {
            "query": evidence_query or user_text,
            "project_slug": project_context.project_slug,
        }
    if resolved_tool_registry is not None:
        agent_kwargs["resolved_tool_registry"] = resolved_tool_registry
    reply = await deps.agent.agent(
        contextual_user_text,
        **_with_optional_trace(deps.agent.agent, agent_kwargs, trace_sink),
    )
    return reply


async def _direct_context_turn(
    context,
    deps: GraphDeps,
    user_text: str,
    recent_messages: list[Any],
    timings: dict,
    *,
    trace_sink=None,
) -> str:
    timings["lane"] = "direct_context"
    timings["direct_context_knowledge_base_id"] = context.knowledge_base_id
    direct_kwargs = {
        "system": build_direct_system(context),
        "metrics": timings,
    }
    return await deps.agent.direct(
        build_direct_user_text(
            current_user_text=user_text,
            recent_messages=recent_messages,
            history_token_budget=DIRECT_HISTORY_TOKEN_BUDGET,
        ),
        **_with_optional_trace(deps.agent.direct, direct_kwargs, trace_sink),
    )


def _finalize_user_visible_reply(
    raw: str,
    *,
    deps: GraphDeps,
    generated: bool,
    user_text: str,
    timings: dict,
    trace_sink: DecisionTraceBuilder,
) -> str:
    """Invoke the reply-policy port once after all routing lanes converge."""
    result = deps.reply_policy.finalize(
        raw,
        generated=generated,
        user_text=user_text,
    )
    if result.trigger is not None:
        timings["safety_trigger"] = result.trigger
    trace_sink.record_decision("safety_verdict", result.verdict)
    return result.output


async def run_manifest_composed_agent(
    user_text: str,
    deps: GraphDeps,
    *,
    policy=None,
    allowed_tools: tuple[str, ...] | None = None,
    lookup_query: str | None = None,
    required_tool: str | None = None,
    required_tool_args: dict | None = None,
    metrics: dict | None = None,
    retry_empty_generation: bool = False,
    trace_sink=None,
) -> str | None:
    """Run an active manifest policy without granting legacy tool authority."""
    if policy is None:
        if deps.runtime_policy is None:
            return None
        policy = await deps.runtime_policy.resolve_active_policy()
    if policy is None:
        return None
    from app.graph.runtime_policy import build_policy_system_prompt

    agent_kwargs = {
        "system": build_policy_system_prompt(policy),
        "retrieval": deps.retrieval,
        "embedder": deps.embedder,
        "allowed_tools": (
            tuple(sorted(policy.tool_registry.names))
            if allowed_tools is None
            else tuple(name for name in allowed_tools if name in policy.tool_registry.names)
        ),
        "resolved_tool_registry": policy.tool_registry.names,
        "make_retrieval": deps.make_retrieval,
        "lookup_query": lookup_query or user_text,
        "metrics": metrics,
        "retry_empty_generation": retry_empty_generation,
    }
    if required_tool is not None:
        agent_kwargs["required_tool"] = required_tool
    if required_tool_args is not None:
        agent_kwargs["required_tool_args"] = required_tool_args
    return await deps.agent.agent(
        user_text,
        **_with_optional_trace(deps.agent.agent, agent_kwargs, trace_sink),
    )


async def _status_heartbeat(zalo, chat_id: str, *, settings) -> None:
    """Keep the channel visibly active while a turn is processing.

    Pulses ``send_chat_action("typing")`` immediately, then every
    ``typing_heartbeat_seconds`` — a real "typing…" indicator on the Bot channel and
    a logged no-op on OA (``ZaloOASender.send_chat_action``). The caller cancels this
    task before dispatching the real answer so the indicator stops on send.

    All send failures are swallowed — status is best-effort and must never break a turn.
    """
    start = time.monotonic()
    next_typing = 0.0
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= next_typing:
            try:
                await zalo.send_chat_action(chat_id, "typing")
            except Exception:  # noqa: BLE001
                pass
            next_typing = elapsed + settings.typing_heartbeat_seconds
        await asyncio.sleep(0.5)


async def _cancel_status_task(task) -> None:
    """Cancel the status heartbeat and drain it so no ack lands after the real send."""
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _finish_terminal_reply(
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    zalo,
    text: str,
    started,
    base_outcome: str,
    *,
    status_task=None,
    stage_timings: dict | None = None,
    trace_sink=None,
):
    """Send a terminal fallback (timeout / error) then record the outcome.

    Shared by the agent-deadline and agent-error paths: refresh to read committed
    version/mode, re-check ownership (a concurrent takeover must not be clobbered),
    send only if still owned, and record so the per-chat mutex clears. Returns the
    TurnOutcome dict (``base_outcome`` unless the send itself failed → ``send_failed``).

    The status heartbeat is cancelled first so its typing indicator stops before
    this terminal reply lands.
    """
    if status_task is not None:
        await _cancel_status_task(status_task)
    await deps.db.refresh(conv)
    lock_owner = state.lock_owner or None
    owned = await svc.claim_send(
        conv,
        version_at_start=state.version_at_start,
        lock_owner=lock_owner,
        pending_message_id=state.pending_message_id,
        reply=text,
        outbox_channel=_channel_for_conversation(conv),
        outbox_payload=_build_outbox_payload(conv.zalo_chat_id, text, state.reply_to_message_id),
    )
    if trace_sink is not None:
        trace_sink.record_decision("ownership_verdict", "claimed" if owned else "suppressed")
    decision_trace = trace_sink.snapshot_payload() if trace_sink is not None else None
    send_result = None
    if owned:
        send_t0 = time.monotonic()
        send_result = await _dispatch_claimed_message(
            svc,
            zalo,
            conv,
            message_id=state.pending_message_id,
            text=text,
            quote_message_id=state.reply_to_message_id,
        )
        if stage_timings is not None:
            stage_timings["send_ms"] = int(round((time.monotonic() - send_t0) * 1000))
        _stamp_outbound_telemetry(stage_timings, send_result)
    _stamp_end_to_end(state, stage_timings)
    # Classify transport errors (same conservative logic as run_turn): a timeout
    # after the request may have reached Zalo → SEND_UNKNOWN (non-retriable), so
    # the error-reply path cannot produce a duplicate on reconcile recovery.
    _suppressed = bool(send_result and getattr(send_result, "suppressed", False))
    _error_class = send_result.error_class if (send_result and not send_result.ok) else None
    statuses = _delivery_statuses(deps)
    _override = (
        statuses.suppressed
        if _suppressed
        else _delivery_status_for_send_error(
            _error_class,
            ok=bool(send_result and send_result.ok),
            send_unknown=statuses.send_unknown,
        )
    )
    await svc.record_bot_outcome(
        conv,
        version_at_start=state.version_at_start,
        reply=text,
        started_at=started,
        sent=bool(send_result and send_result.ok),
        pending_message_id=state.pending_message_id,
        external_error=send_result.error if send_result and not send_result.ok else None,
        zalo_message_id=send_result.msg_id if send_result else None,
        stage_timings=stage_timings,
        lock_owner=lock_owner,
        trace_id=state.trace_id or None,
        delivery_status=_override,
        decision_trace=decision_trace,
        outbox_channel=_channel_for_conversation(conv),
        outbox_payload=_build_outbox_payload(conv.zalo_chat_id, text, state.reply_to_message_id),
    )
    if _suppressed:
        outcome = "suppressed"
    elif send_result is None or send_result.ok:
        outcome = base_outcome
    elif _override is not None and _override.value == "SEND_UNKNOWN":
        outcome = "send_unknown"
    else:
        outcome = "send_failed"
    return {"outcome": outcome, "reply": text}


def _stamp_db(timings: dict, key: str, t0: float) -> None:
    """Accumulate wall-clock of one DB call into timings['db_ms'].

    ``key`` is recorded into db_breakdown for per-call granularity when the
    dashboard needs to localize a slow query. db_ms is the aggregate the
    percentile chart reads.
    """
    elapsed = int(round((time.monotonic() - t0) * 1000))
    timings["db_ms"] = timings.get("db_ms", 0) + elapsed
    breakdown = timings.setdefault("db_breakdown", {})
    breakdown[key] = breakdown.get(key, 0) + elapsed


def _faq_should_abstain(bypass, settings) -> bool:
    """True when the top FAQ match is only marginally better than the runner-up.

    A low margin (score - runner_up_score < faq_abstain_margin) means the
    semantic match is low-confidence — the top hit may not be the right answer.
    Fall through to the LLM instead. Returns False when there's no runner-up
    (single result) or the margin setting is 0 (legacy behavior).
    """
    margin = settings.faq_abstain_margin
    if margin <= 0:
        return False
    if bypass.runner_up_score is None:
        return False
    return (bypass.score - bypass.runner_up_score) < margin


# Volatile operational claims normally avoid FAQ prose. Vacancy threads are the
# exception: published, effective-dated canonical FAQ answers are deterministic
# evidence and take precedence over free-form generation.
# The legacy service path takes an explicit ``published_vacancy_evidence`` flag
# when it is used; the graph cannot import service modules across this boundary.
_FAQ_BYPASS_VOLATILE_MARKERS = (
    "lương",
    "thu nhập",
    "ca làm",
    "giờ làm",
    "tăng ca",
    "phụ cấp",
    "xe đưa đón",
    "tuyến xe",
    "xe lúc",
    "xe mấy",
    "đón xe",
    "số điện thoại",
    "hotline",
    "liên hệ",
)

def _recent_vacancy_query(recent_messages: list[Any]) -> str | None:
    for message in reversed(recent_messages):
        sender = getattr(message, "sender", "")
        sender_value = getattr(sender, "value", sender)
        body = str(getattr(message, "body", "") or "")
        if sender_value == "WORKER" and is_vacancy_lookup(body):
            return body
    return None


def _vacancy_required_args(user_text: str) -> dict:
    """Build forced ``list_active_jobs`` args for a vacancy-listing turn.

    Always widens ``top_k`` to 10 so the full catalog is visible. When the user
    asked to sort by salary ("sắp xếp theo lương từ cao xuống thấp"), the detected
    direction is injected here because ``required_tool_args`` replaces the model's
    own arguments for the forced first call — without this the LLM's ``sort_by``
    would be dropped on the authoritative tool round. The same applies to recency
    ("gần nhất" / "mới nhất" -> ``created_at``).
    """
    args: dict = {"top_k": 10}
    sort_by = detect_salary_sort_intent(user_text)
    if sort_by is None:
        sort_by = detect_recency_sort_intent(user_text)
    if sort_by is not None:
        args["sort_by"] = sort_by
    return args


def _vacancy_evidence_query(
    user_text: str,
    recent_messages: list[Any],
    *,
    focused_project: bool = False,
) -> str | None:
    """Build detail evidence text while preferring durable Project focus over chat prose."""
    if is_vacancy_lookup(user_text):
        return None
    if route_turn(user_text).intent != "faq_detail":
        return None
    if focused_project:
        return user_text
    vacancy_query = _recent_vacancy_query(recent_messages)
    return f"{vacancy_query}\n{user_text}" if vacancy_query else None


def _faq_bypass_allowed(user_text: str, recent_messages: list[Any]) -> bool:
    """Prefer canonical vacancy FAQs; keep other volatile claims on live paths."""
    if is_vacancy_lookup(user_text):
        return False
    normalized = user_text.casefold()
    if _vacancy_evidence_query(user_text, recent_messages) is not None:
        # Published, effective-dated canonical FAQs are the preferred deterministic
        # answer for vacancy threads; the confidence/margin gate still may abstain.
        return True
    if any(marker in normalized for marker in _FAQ_BYPASS_VOLATILE_MARKERS):
        return False
    return True


async def run_turn(state: BotRunState, deps: GraphDeps) -> TurnOutcome:
    """Execute one bot turn end-to-end and persist the SENT/SUPPRESSED outcome."""
    timings: dict = {"execution_source": state.execution_source}
    svc = deps.conversation

    db_t0 = time.monotonic()
    conv = await svc.get(uuid.UUID(state.conversation_id))
    _stamp_db(timings, "get_conversation", db_t0)
    if conv is None:
        return {"outcome": "error", "reason": "conversation_not_found"}
    lock_owner = state.lock_owner or None
    has_runtime_stamp = bool(
        state.runtime_revision_id
        and state.authority_generation is not None
        and state.runtime_fingerprint
    )
    if has_runtime_stamp:
        is_current = (
            deps.runtime_policy is not None
            and await deps.runtime_policy.runtime_stamp_is_current(
                revision_id=state.runtime_revision_id,
                authority_generation=state.authority_generation,
                runtime_fingerprint=state.runtime_fingerprint,
            )
        )
        if not is_current:
            if lock_owner:
                await svc.release_lock(conv, lock_owner=lock_owner)
            return {"outcome": "suppressed", "reason": "stale_runtime_authority"}
    manifest_policy = None
    if has_runtime_stamp:
        if deps.runtime_policy is None:
            if lock_owner:
                await svc.release_lock(conv, lock_owner=lock_owner)
            return {"outcome": "suppressed", "reason": "missing_runtime_policy"}
        manifest_policy = await deps.runtime_policy.resolve_active_policy()
        if manifest_policy is None:
            if lock_owner:
                await svc.release_lock(conv, lock_owner=lock_owner)
            return {"outcome": "suppressed", "reason": "inactive_runtime_policy"}
    elif deps.runtime_policy is not None:
        # A clean cutover never lets pre-authority jobs inherit today's
        # capabilities.  Tests and explicitly legacy deployments inject no
        # runtime policy and retain their existing behavior.
        if await deps.runtime_policy.resolve_active_policy() is not None:
            if lock_owner:
                await svc.release_lock(conv, lock_owner=lock_owner)
            return {"outcome": "suppressed", "reason": "missing_runtime_authority"}
    if lock_owner:
        db_t0 = time.monotonic()
        await deps.db.refresh(conv)
        ok = await svc.recheck_ownership(conv, state.version_at_start, lock_owner=lock_owner)
        _stamp_db(timings, "recheck_ownership", db_t0)
        if not ok:
            return {"outcome": "suppressed", "reason": "lock_owner_lost"}

    settings = get_settings()

    # Fetch the OA display name/avatar only after runtime + lock ownership are
    # proven, but before lead context is assembled. The webhook stays fast and
    # stale jobs never spend a provider call. A strict ceiling preserves the
    # answer budget; persistence_low remains the eventual-consistency fallback.
    if (
        getattr(conv, "zalo_channel", "bot") == "oa"
        and deps.enrich_oa_profile is not None
        and conv.zalo_chat_id
    ):
        profile_t0 = time.monotonic()
        user_id = conv.zalo_chat_id.removeprefix("oa:")
        profile_budget = min(
            OA_PROFILE_LOOKUP_TIMEOUT_SECONDS,
            max(0.0, _remaining(state) - settings.soft_fallback_remaining),
        )
        if profile_budget <= 0:
            timings["oa_profile_result"] = "skipped_deadline"
        else:
            try:
                enriched = await asyncio.wait_for(
                    deps.enrich_oa_profile(conv.zalo_chat_id, user_id),
                    timeout=profile_budget,
                )
                timings["oa_profile_result"] = "enriched" if enriched else "unchanged"
            except asyncio.TimeoutError:
                timings["oa_profile_result"] = "timeout"
                logger.info("oa profile enrichment timed out before chat turn")
                try:
                    await deps.db.rollback()
                    await deps.db.refresh(conv)
                except Exception as recovery_exc:  # noqa: BLE001
                    logger.debug(
                        "oa profile enrichment timeout recovery failed error_type=%s",
                        type(recovery_exc).__name__,
                    )
            except Exception as profile_exc:  # noqa: BLE001 — optional profile data
                timings["oa_profile_result"] = "error"
                logger.warning(
                    "oa profile enrichment failed before chat turn error_type=%s",
                    type(profile_exc).__name__,
                )
                try:
                    await deps.db.rollback()
                    await deps.db.refresh(conv)
                except Exception as recovery_exc:  # noqa: BLE001
                    logger.debug(
                        "oa profile enrichment recovery failed error_type=%s",
                        type(recovery_exc).__name__,
                    )
        timings["oa_profile_ms"] = int(round((time.monotonic() - profile_t0) * 1000))
    zalo = _zalo_for_conversation(deps, conv)

    # Active-status heartbeat: native typing pulses while the turn processes.
    # Started right after the sender is resolved (before last_messages / pending)
    # so the indicator appears as early as possible. Cancelled before every real
    # send so the indicator stops on the answer.
    status_task = asyncio.create_task(_status_heartbeat(zalo, conv.zalo_chat_id, settings=settings))
    db_t0 = time.monotonic()
    recent_messages = await svc.last_messages(conv, limit=RECENT_HISTORY_LIMIT)
    _stamp_db(timings, "last_messages", db_t0)
    started = _now()
    db_t0 = time.monotonic()
    pending_kwargs: dict[str, object] = {}
    if (
        state.runtime_revision_id
        and state.authority_generation is not None
        and state.runtime_fingerprint
    ):
        pending_kwargs = {
            "runtime_revision_id": uuid.UUID(state.runtime_revision_id),
            "authority_generation": state.authority_generation,
            "runtime_fingerprint": state.runtime_fingerprint,
        }
    pending_msg = await svc.record_bot_pending(conv, **pending_kwargs)
    _stamp_db(timings, "record_bot_pending", db_t0)
    state.pending_message_id = pending_msg.id

    # Per-stage timing accumulator. The enqueue/preamble slice is derived from
    # the worker's epoch stamps (state.preamble_start_epoch / received_at_epoch);
    # intra-turn stages use time.monotonic() deltas against t0. Threaded into
    # record_bot_outcome -> BotRun.stage_timings for the performance dashboard.
    # ``timings`` was initialized before the first DB call (db_ms accumulates
    # across the whole turn, including the pre-t0 conversation fetch).
    turn_start_epoch = time.time()
    if state.queue_depth is not None:
        timings["queue_depth"] = state.queue_depth
    if state.received_at_epoch > 0 and state.preamble_start_epoch > 0:
        timings["webhook_to_pickup_ms"] = max(
            0, int(round((state.preamble_start_epoch - state.received_at_epoch) * 1000))
        )
    if state.preamble_start_epoch > 0:
        timings["preamble_ms"] = max(
            0, int(round((turn_start_epoch - state.preamble_start_epoch) * 1000))
        )
    t0 = time.monotonic()
    trace_sink = DecisionTraceBuilder()
    turn_route = route_turn(state.user_text)
    trace_sink.record_decision("route_selected", turn_route.reason)

    try:
        candidate = ""
        generated_reply = False
        outcome_label = "sent"
        faq_metadata: dict | None = None
        from app.recruitment.domain.provider import provider_from_conversation

        provider = provider_from_conversation(conv)

        project_context = None
        if deps.direct_context is not None and turn_route.reason != "vacancy_listing":
            if hasattr(deps.direct_context, "resolve"):
                project_context = await deps.direct_context.resolve(conv, state.user_text)
            elif hasattr(deps.direct_context, "active_context"):
                from app.graph.direct_context import ProjectTurnContext

                legacy_direct = await deps.direct_context.active_context()
                if legacy_direct is not None:
                    project_context = ProjectTurnContext(
                        state="FOCUSED",
                        knowledge_mode="DIRECT_CONTEXT",
                        direct_context=legacy_direct,
                    )
        direct_context = project_context.direct_context if project_context is not None else None
        if project_context is not None:
            timings["project_context_state"] = project_context.state
            if project_context.project_id:
                timings["focused_project_id"] = project_context.project_id
            if project_context.knowledge_mode:
                timings["knowledge_mode"] = project_context.knowledge_mode
        recruitment_capabilities = (
            frozenset(manifest_policy.capability_ids) if manifest_policy is not None else None
        )
        recruitment_enabled = manifest_policy is None or manifest_policy.pack_key == "recruitment"
        # Candidate extraction remains recruitment-scoped. Final replies do not
        # use a template fast lane: every normal user message reaches the LLM so
        # it can use the current project context and conversation history.
        allow_recruitment_fast_lane = (
            recruitment_enabled
            and (
                recruitment_capabilities is None
                or "candidate_intake" in recruitment_capabilities
            )
        )
        allow_legacy_faq_bypass = False

        # --- deterministic FAQ-bypass cascade (retired as a final-answer path) ---
        # If re-enabled in the future, it must only provide evidence to the LLM;
        # it must never return a final answer directly. It is currently disabled.
        # It formerly answered
        # directly from the knowledge base (0¢, sub-50ms on an embedding-cache hit);
        # on any miss / ambiguity / timeout it abstains (None) and the turn falls
        # through to the agent unchanged. Time-boxed so a cold embed can never burn
        # the turn deadline. None in graph unit tests (no bypass wired).
        bypass = None
        if (
            direct_context is None
            and allow_legacy_faq_bypass
            and deps.faq_bypass is not None
            and _faq_bypass_allowed(state.user_text, recent_messages)
        ):
            try:
                # Bound the bypass by both the soft cap and the propagated turn
                # deadline (minus the send margin) so a cold-embed bypass can
                # never consume the sliver the agent needs on a tight turn.
                bypass_budget = min(
                    settings.soft_fallback_remaining,
                    max(0.0, _remaining(state) - settings.send_margin_seconds),
                )
                bypass = await asyncio.wait_for(
                    deps.faq_bypass.try_answer(
                        _vacancy_evidence_query(state.user_text, recent_messages)
                        or state.user_text
                    ),
                    timeout=bypass_budget,
                )
            except asyncio.TimeoutError:
                logger.info(
                    "faq_bypass timed out (%.1fs); falling through to agent",
                    settings.soft_fallback_remaining,
                )
                bypass = None
            except Exception:  # noqa: BLE001 — bypass must never break a turn
                logger.warning("faq_bypass adapter raised; abstaining", exc_info=True)
                # The bypass adapter shares this turn's session (RetrievalRepository
                # on deps.db). If it raised on a DB error the session is now in a
                # needs-rollback state; clear it so the next DB op (refresh /
                # claim_send below) does not cascade into a rollback error. Safe
                # because record_bot_pending above already committed its row.
                try:
                    await deps.db.rollback()
                except Exception:  # noqa: BLE001 — best-effort; worker_session also rolls back
                    logger.debug("faq_bypass recovery rollback failed", exc_info=True)
                bypass = None

        # Abstention check: if the top FAQ match is only marginally better than
        # the runner-up, record the abstention and clear bypass so the turn falls
        # through to the agent branch below (the elif chain cannot fall through
        # an already-matched branch).
        if bypass is not None and _faq_should_abstain(bypass, settings):
            timings["faq_bypass_ms"] = int(round(bypass.latency_ms))
            timings["faq_abstained"] = True
            faq_metadata = {
                "faq_id": bypass.faq_id,
                "tier": bypass.tier,
                "similarity_score": bypass.score,
                "runner_up_score": bypass.runner_up_score,
                "abstained": True,
            }
            logger.info(
                "faq_bypass abstained (low margin) tier=%s score=%.3f runner_up=%.3f "
                "margin=%.3f threshold=%.3f — falling through to agent",
                bypass.tier,
                bypass.score,
                bypass.runner_up_score or 0.0,
                bypass.score - (bypass.runner_up_score or 0.0),
                settings.faq_abstain_margin,
            )
            bypass = None

        if project_context is not None and project_context.clarification:
            trace_sink.record_decision("context_selected", "project_clarification")
            trace_sink.record_decision("lane_selected", "project_clarification")
            candidate = project_context.clarification
            timings["lane"] = "project_clarification"
            outcome_label = "project_clarification"
        elif direct_context is not None and turn_route.reason != "vacancy_listing":
            trace_sink.record_decision("context_selected", "direct_context")
            trace_sink.record_decision("lane_selected", "direct_context")
            raw = await _direct_context_turn(
                direct_context,
                deps,
                state.user_text,
                recent_messages,
                timings,
                trace_sink=trace_sink,
            )
            state.reply = raw
            candidate = raw
            generated_reply = True
            outcome_label = "direct_context"
        elif bypass is not None:
            trace_sink.record_decision("context_selected", "faq_bypass")
            trace_sink.record_decision("lane_selected", "faq_bypass")
            timings["lane"] = "faq_bypass"
            timings["faq_bypass_ms"] = int(round(bypass.latency_ms))
            # Admin-authored canonical FAQ text — sent verbatim, like the template
            # lane above (fast_safety_filter is tuned for LLM output, not curated text).
            candidate = bypass.answer
            outcome_label = "faq_bypass"
            # Stamp provenance so the threshold can be tuned from production data.
            faq_metadata = {
                "faq_id": bypass.faq_id,
                "tier": bypass.tier,
                "similarity_score": bypass.score,
                "runner_up_score": bypass.runner_up_score,
                "abstained": False,
            }
            logger.info(
                "faq_bypass hit tier=%s score=%.3f reason=%s faq_id=%s",
                bypass.tier,
                bypass.score,
                bypass.reason,
                bypass.faq_id,
            )
        else:
            trace_sink.record_decision(
                "context_selected",
                "focused_rag"
                if (
                    project_context is not None
                    and project_context.state == "FOCUSED"
                    and project_context.knowledge_mode == "RAG"
                )
                else "agent_graph",
            )
            trace_sink.record_decision("lane_selected", "agent")
            timings["lane"] = "agent"
            # --- agent (runs to completion; NO hard cap) ---
            # The propagated deadline is advisory only — it bounds the FAQ-bypass
            # lookup above, never the agent. Cancelling a live LLM call mid-generation
            # produced excessive TIMEOUT fallbacks in prod, so the agent is allowed to
            # finish and its real answer is sent. A genuinely hung provider call is
            # reaped by the RQ job_timeout backstop (>> any realistic turn) and the
            # turn is recovered by the reconcile sweep.
            try:
                agent_kwargs = {
                    "provider": provider,
                    "chat_id": conv.zalo_chat_id,
                    "recent_messages": recent_messages,
                    "timings": timings,
                }
                if project_context is not None:
                    agent_kwargs["project_context"] = project_context
                if manifest_policy is not None:
                    agent_kwargs["manifest_policy"] = manifest_policy
                raw = await _agent_turn(
                    state,
                    deps,
                    state.user_text,
                    **_with_optional_trace(_agent_turn, agent_kwargs, trace_sink),
                )
            except LLMThrottled as exc:
                # The worker owns the static degradation reply, but the
                # request-local trace would otherwise be lost at this boundary.
                # Transfer only the validated snapshot, never the live builder
                # or any prompt, exception, or tool payload.
                trace_sink.record_decision("degradation_reason", "llm_throttled")
                exc.decision_trace = trace_sink.snapshot_payload()
                raise  # let worker handle degradation msg (no LLM call)
            except Exception as exc:  # noqa: BLE001 — agent blew up -> graceful fallback
                logger.warning("agent error: %s", exc)
                # The agent path may have used deps.db (lead / system-prompt reads).
                # Clear any aborted transaction before the error-reply path reuses
                # the session (claim_send / record_bot_outcome), otherwise the
                # recovery itself raises a rollback error. Safe: record_bot_pending
                # already committed.
                try:
                    await deps.db.rollback()
                except Exception:  # noqa: BLE001 — best-effort; worker_session also rolls back
                    logger.debug("agent-error recovery rollback failed", exc_info=True)
                timings["total_ms"] = int(round((time.monotonic() - t0) * 1000))
                return await _finish_terminal_reply(
                    state,
                    deps,
                    conv,
                    svc,
                    zalo,
                    ERROR_REPLY,
                    started,
                    "error",
                    status_task=status_task,
                    stage_timings=timings,
                    trace_sink=trace_sink,
                )

            state.reply = raw
            candidate = raw
            generated_reply = True

            # --- deterministic safety gate (no LLM judge) ---
            # The fast filter strips <think>/markdown/code-fences from the raw
            # reply and flags three triggers, each resolved deterministically:
            #   - blocklist hit     → retry_exhausted_fallback (hard redirect)
            #   - empty/risk-regex  → retry_exhausted_fallback (redirect)
            #   - over-long (>1800) → truncate_for_chat, then SEND (already
            #     applied by fast_safety_filter — a detailed job-presentation
            #     reply is legitimate content, not a safety issue)
            # This replaces the former LLM safety judge (a ~10s second model call
            # that p50'd at 10.3s). The judge added latency without adding safety.
        # All routing lanes converge on one content boundary before persistence
        # and transport. Generated replies receive the full safety policy;
        # curated replies preserve authored formatting while still enforcing the
        # invariant that provider reasoning tags never reach an end user.
        candidate = _finalize_user_visible_reply(
            candidate,
            deps=deps,
            generated=generated_reply,
            user_text=state.user_text,
            timings=timings,
            trace_sink=trace_sink,
        )

        # Defense-in-depth: every lane should already produce non-empty content
        # (fast_safety_filter falls back to FALLBACK_REPLY; the safety gate above
        # redirects to retry_exhausted_fallback), but an empty candidate reaching
        # here would be persisted as body="" (via claim_send / record_bot_outcome)
        # and render in the recruiter console as a blank "Gửi lỗi" bubble with no
        # indication of what the bot tried to send. Fall back to the generic
        # technical-issue reply so a failed send is always diagnosable.
        if not (candidate or "").strip():
            candidate = ERROR_REPLY

        # --- pre_send_guard: atomically claim the send (PENDING→SENDING), gated
        # server-side on version + lock_owner + lock liveness. Closes both the
        # crash-window (a stale SENDING row left by a post-send crash is reconciled
        # as sent-but-unconfirmed, at-most-once) and the recheck→send TOCTOU (a
        # takeover or newer inbound bumping version before the claim yields rowcount
        # 0 → suppress). refresh() keeps the bound conv on committed state. ---
        db_t0 = time.monotonic()
        await deps.db.refresh(conv)
        owned = await svc.claim_send(
            conv,
            version_at_start=state.version_at_start,
            lock_owner=lock_owner,
            pending_message_id=state.pending_message_id,
            reply=candidate,
            outbox_channel=_channel_for_conversation(conv),
            outbox_payload=_build_outbox_payload(
                conv.zalo_chat_id, candidate, state.reply_to_message_id
            ),
        )
        _stamp_db(timings, "claim_send", db_t0)
        if owned:
            trace_sink.record_decision("ownership_verdict", "claimed")
            decision_trace = trace_sink.snapshot_payload()
            await _cancel_status_task(status_task)
            send_t0 = time.monotonic()
            send_result = await _dispatch_claimed_message(
                svc,
                zalo,
                conv,
                message_id=state.pending_message_id,
                text=candidate,
                quote_message_id=state.reply_to_message_id,
            )
            timings["send_ms"] = int(round((time.monotonic() - send_t0) * 1000))
            _stamp_outbound_telemetry(timings, send_result)
            timings["total_ms"] = int(round((time.monotonic() - t0) * 1000))
            _stamp_end_to_end(state, timings)
            db_t0 = time.monotonic()
            # Classify transport failures: ambiguous (timeout/reset after the
            # request may have reached Zalo) → SEND_UNKNOWN (non-retriable); every
            # other failure stays FAILED (the reconciler may re-enqueue).
            send_suppressed = bool(getattr(send_result, "suppressed", False))
            send_error_class = send_result.error_class if not send_result.ok else None
            statuses = _delivery_statuses(deps)
            override_status: Any | None = None
            if send_suppressed:
                override_status = statuses.suppressed
            elif send_error_class in AMBIGUOUS_SEND_CLASSES:
                override_status = statuses.send_unknown
            await svc.record_bot_outcome(
                conv,
                version_at_start=state.version_at_start,
                reply=candidate,
                started_at=started,
                sent=send_result.ok,
                pending_message_id=state.pending_message_id,
                external_error=None if send_result.ok else send_result.error,
                zalo_message_id=send_result.msg_id,
                stage_timings=timings,
                lock_owner=lock_owner,
                delivery_status=override_status,
                trace_id=state.trace_id or None,
                outcome_metadata=faq_metadata,
                decision_trace=decision_trace,
                outbox_channel=_channel_for_conversation(conv),
                outbox_payload=_build_outbox_payload(
                    conv.zalo_chat_id, candidate, state.reply_to_message_id
                ),
            )
            _stamp_db(timings, "record_bot_outcome", db_t0)
            if send_suppressed:
                return {"outcome": "suppressed", "reason": send_result.error, "reply": candidate}
            if not send_result.ok:
                return {
                    "outcome": (
                        "send_unknown"
                        if override_status is statuses.send_unknown
                        else "send_failed"
                    ),
                    "reason": send_result.error,
                    "reply": candidate,
                }
            # The post-send extraction owns lead, memory, and contact intent. Every
            # LLM-generated turn is eligible for recruitment extraction.
            pure_fast_pleasantry = False
            # Candidate extraction owns recruitment lead/contact state. It is
            # not a generic post-send hook, so never enqueue it for a
            # manifest-composed non-recruitment installation.
            if (
                deps.persist is not None
                and allow_recruitment_fast_lane
                and not pure_fast_pleasantry
            ):
                persist_job = {
                    "chat_id": conv.zalo_chat_id,
                    "user_text": state.user_text,
                    "bot_output": candidate,
                    "conversation_version": state.version_at_start,
                }
                if manifest_policy is not None:
                    persist_job.update(
                        {
                            "runtime_revision_id": manifest_policy.revision_id,
                            "authority_generation": state.authority_generation,
                            "runtime_fingerprint": manifest_policy.fingerprint_checksum,
                        }
                    )
                deps.persist(persist_job)
            return {"outcome": outcome_label, "reply": candidate}

        timings["total_ms"] = int(round((time.monotonic() - t0) * 1000))
        _stamp_end_to_end(state, timings)
        trace_sink.record_decision("ownership_verdict", "suppressed")
        decision_trace = trace_sink.snapshot_payload()
        db_t0 = time.monotonic()
        await svc.record_bot_outcome(
            conv,
            version_at_start=state.version_at_start,
            reply=candidate,
            started_at=started,
            sent=False,
            pending_message_id=state.pending_message_id,
            stage_timings=timings,
            lock_owner=lock_owner,
            trace_id=state.trace_id or None,
            outcome_metadata=faq_metadata,
            decision_trace=decision_trace,
        )
        _stamp_db(timings, "record_bot_outcome", db_t0)
        return {"outcome": "suppressed", "reply": candidate}
    finally:
        await _cancel_status_task(status_task)
