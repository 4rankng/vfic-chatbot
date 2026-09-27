"""Answer lanes: clarification → direct context → agent, and the route
arguments each of them needs.

``_resolve_lane`` picks the lane, runs it, and converts the agent lane's crash
into a stand-down through the authority gate (the only lane that can fail).
Everything a lane needs to build its prompt — the tool allowlist, the forced
``required_tool_args`` for vacancy listing and income comparison, the ground
evidence query — lives here rather than in the turn entrypoint, so a routing
change is a change to this module only.

``_agent_turn`` is injected into ``_resolve_lane`` by ``run_turn``: the
composition point stays in ``runner.py`` and this module keeps no back-reference
to it.
"""

from __future__ import annotations

import logging
import time
from inspect import Parameter, signature
from typing import Any, NamedTuple

from app.graph.authority import _authority_gate
from app.graph.decision_trace import DecisionTraceBuilder
from app.graph.direct_context import (
    build_direct_system,
    build_direct_user_text,
)
from app.graph.llm_semaphore import LLMThrottled
from app.graph.ports import TurnDecisions
from app.graph.progressive import _ProgressiveStream
from app.graph.prompt_context import build_agent_user_text
from app.graph.router import (
    TurnRoute,
    route_from_decisions,
    routing_instruction,
    should_use_fast_model,
)
from app.graph.runtime_policy import TINGTING_TOOL_NAMES
from app.graph.schemas import ROUTE_CONFIDENCE_FLOOR
from app.graph.tingting_guide import (
    TINGTING_RESET_REDIRECT_REPLY,
    tingting_api_prompt_block,
)
from app.graph.types import BotRunState, GraphDeps, TurnOutcome
from app.recruitment.domain.recommendation import (
    is_salary_profile_statement,
    parse_salary_band,
)
from app.shared.domain.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)
DIRECT_HISTORY_TOKEN_BUDGET = 12_000
_INCOME_COMPARE_HINT = (
    "Ý định: hỏi mốc thu nhập chung khi chưa chốt dự án. Phải dùng compare_income trước, "
    "trả lời theo từng dự án bằng đúng cơ sở dữ liệu (thu nhập tháng, bình quân năm chia 12, "
    "thưởng, kỳ lương), không gộp các cơ sở tính thành một con số duy nhất."
)

# The support OA itself serves the reset flow only; every other message hands the
# employee to a human instead of answering (operator requirement).
TINGTING_HANDOFF_REPLY = "Vui lòng chờ chuyên viên tư vấn liên hệ."
TINGTING_HANDOFF_REASON = "tingting_support_handoff"


# The legacy keyword volatile-markers list and the recent-vacancy body scan
# are gone with the keyword router: the Jev fan-out answers both judgments
# (vacancy_listing, recent_vacancy) with calibrated probabilities in the same
# per-turn call.


def _optional_policy_kwargs(callable_obj, policy: dict) -> dict:
    """Keep only the policy kwargs the target function declares.

    The real ``_agent_turn`` accepts them; a test double (or an installation's
    replacement for it) may predate the keyword, and a missing keyword must not
    turn a live reply into an error. Production always calls the real function,
    so this filter can never drop the channel gate from a real turn.
    """
    try:
        parameters = signature(callable_obj).parameters
    except (TypeError, ValueError):
        return {}
    if any(parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return dict(policy)
    return {name: value for name, value in policy.items() if name in parameters}


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


async def _tingting_support_handoff(state: BotRunState, deps: GraphDeps) -> None:
    """Flag the support-OA conversation for a human.

    The reply tells the employee to wait for a consultant; without this
    transition nobody would know to contact them. Best-effort: a failure must
    never swallow the reply the employee is waiting for.
    """
    try:
        conv = await deps.conversation.get(state.conversation_id)
        if conv is None:
            return
        # ``conv`` is loaded fresh here, so its version is the current one: the
        # transition is guarded against a concurrent write, not against the
        # version the turn started with (that one moved when the inbound landed).
        await deps.conversation.escalate_extracted_intent(
            conv,
            reason=TINGTING_HANDOFF_REASON,
            confidence=1.0,
            expected_version=conv.version,
        )
    except Exception:  # noqa: BLE001 — the handoff is bookkeeping, never the answer
        logger.warning("tingting support handoff failed", exc_info=True)


async def _tingting_reset_allowed(deps: GraphDeps, conv) -> bool:
    """Whether this conversation's channel may run the TingTing reset flow.

    The flow belongs to the TingTing Zalo OA: a message on the recruitment Bot
    channel or on Messenger must never be offered it (operator requirement), so
    anything but a ``zalo_oa`` conversation is refused here. The stored
    ``tingting_reset_oa_id`` pin then narrows it to one OA account. Fail-closed
    on a configuration read error: no guide, no tools, and the honest
    wrong-channel reply.
    """
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY

    identity = getattr(conv, "channel_identity", None)
    if identity is None or str(getattr(identity, "provider", "") or "") != "zalo_oa":
        return False
    if str(getattr(identity, "account_key", "") or "") != TINGTING_OA_ACCOUNT_KEY:
        # The flow runs on the linked support OA only. Every other Zalo OA
        # conversation — including the original recruitment OA — is refused.
        return False
    reader = getattr(deps.retrieval, "tingting_reset_oa_id", None)
    if reader is None:
        return False
    try:
        pinned = str(await reader() or "").strip()
    except Exception:  # noqa: BLE001 — a config read must not break a turn
        logger.warning("tingting reset scope read failed", exc_info=True)
        return False
    # The pin follows the verified link (TingTingOaLinkService), so a broken or
    # removed link turns the flow off rather than leaving it open.
    return pinned == TINGTING_OA_ACCOUNT_KEY


def _vacancy_required_args(decisions: TurnDecisions) -> dict:
    """Build forced ``list_active_jobs`` args for a vacancy-listing turn.

    Always widens ``top_k`` to 10 so the full catalog is visible. When the
    candidate asked to sort the catalog (salary direction or newest-first),
    the Jev ``sort_by`` judgment is injected here because ``required_tool_args``
    replaces the model's own arguments for the forced first call — without
    this the LLM's ``sort_by`` would be dropped on the authoritative round.
    """
    args: dict = {"top_k": 10}
    if decisions.sort_by:
        args["sort_by"] = decisions.sort_by
    return args


def _compare_income_required_args(
    user_text: str,
    *,
    route_intent: str,
    project_context: Any | None,
) -> dict[str, int] | None:
    if route_intent not in {"faq_detail", "general"}:
        return None
    if project_context is not None and getattr(project_context, "state", None) == "FOCUSED":
        return None
    normalized = normalize_vietnamese_text(user_text or "")
    if "luong" not in normalized and "thu nhap" not in normalized:
        return None
    if is_salary_profile_statement(normalized):
        return None
    _minimum, target = parse_salary_band(normalized)
    if target is None:
        return None
    return {"target_monthly_vnd": int(target)}


def _vacancy_evidence_query(
    user_text: str,
    decisions: TurnDecisions,
    recent_messages: list[Any] | None = None,
    *,
    focused_project: bool = False,
) -> str | None:
    """Build detail evidence text while preferring durable Project focus over chat prose."""
    if decisions.vacancy_listing:
        return None
    if decisions.intent != "faq_detail":
        return None
    if focused_project:
        return user_text
    if decisions.recent_vacancy:
        # The Jev flag marks a vacancy thread; the candidate bodies supply the
        # thread context the keyword scan used to stitch (the flag cannot name
        # the exact message, so all of them ride along as retrieval context).
        bodies = [
            body
            for message in (recent_messages or [])
            if (body := str(getattr(message, "body", "") or "").strip())
        ]
        if bodies:
            return "\n".join(bodies) + "\n" + user_text
    return None


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
    }
    if required_tool is not None:
        agent_kwargs["required_tool"] = required_tool
    if required_tool_args is not None:
        agent_kwargs["required_tool_args"] = required_tool_args
    return await deps.agent.agent(
        user_text,
        **_with_optional_trace(deps.agent.agent, agent_kwargs, trace_sink),
    )


async def _agent_turn(
    state: BotRunState,
    deps: GraphDeps,
    user_text: str,
    *,
    provider: str,
    chat_id: str,
    recent_messages: list[Any],
    contact_id: str | None = None,
    timings: dict | None = None,
    trace_sink=None,
    manifest_policy=None,
    project_context=None,
    decisions: TurnDecisions | None = None,
    lead_row: dict | None = None,
    tingting_reset_allowed: bool = False,
    on_delta=None,
    on_evidence=None,
) -> str:
    route = route_from_decisions(user_text, decisions or TurnDecisions(degraded=True))
    if route.intent == "employee_support" and not tingting_reset_allowed:
        # Employee-account support belongs to the TingTing OA: elsewhere the turn
        # is answered with the operator's exact pointer to that OA instead of
        # running a flow this channel cannot serve (the guide and the reset tools
        # are not bound here either).
        if trace_sink is not None:
            trace_sink.record_decision("tingting_scope", "channel_not_allowed")
        return TINGTING_RESET_REDIRECT_REPLY
    if tingting_reset_allowed and route.intent != "employee_support":
        # This IS the support OA: it serves the reset flow and nothing else, so
        # any other message goes to a human rather than being answered by the bot.
        if trace_sink is not None:
            trace_sink.record_decision("tingting_scope", "support_only_handoff")
        await _tingting_support_handoff(state, deps)
        return TINGTING_HANDOFF_REPLY
    focused_project = bool(
        project_context is not None and getattr(project_context, "state", None) == "FOCUSED"
    )
    evidence_query = _vacancy_evidence_query(
        user_text,
        decisions,
        recent_messages,
        focused_project=focused_project,
    )
    vacancy_catalog_required = route.reason == "vacancy_listing" or (
        route.intent == "general" and decisions.recent_vacancy
    )
    compare_income_required_args = _compare_income_required_args(
        user_text,
        route_intent=route.intent,
        project_context=project_context,
    )
    required_authority_tool = (
        "list_active_jobs"
        if vacancy_catalog_required
        else "compare_income" if compare_income_required_args is not None else None
    )
    if manifest_policy is not None and manifest_policy.pack_key != "recruitment":
        allowed_tools = (
            route.tools if route.confidence >= ROUTE_CONFIDENCE_FLOOR else None
        )
        if vacancy_catalog_required:
            allowed_tools = ("list_active_jobs",)
        elif compare_income_required_args is not None:
            allowed_tools = ("compare_income",)
        if allowed_tools is not None:
            allowed_tools = tuple(
                name for name in allowed_tools if name in manifest_policy.tool_registry.names
            )
        if required_authority_tool is not None and not manifest_policy.tool_registry.allows(
            required_authority_tool
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
            required_tool=(
                "list_active_jobs"
                if vacancy_catalog_required
                else "compare_income" if compare_income_required_args is not None else None
            ),
            required_tool_args=(
                _vacancy_required_args(decisions)
                if vacancy_catalog_required
                else compare_income_required_args
            ),
            metrics=timings,
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

    # Never print a guide for a tool this turn cannot bind: an installation
    # without the knowledge capability lacks the reset tools, and pointing the model
    # at endpoints it cannot reach reads as an invitation to invent one.
    api_tool_registry = getattr(manifest_policy, "tool_registry", None)

    # ``tingting_reset_allowed`` rides the turn (see ``run_turn``): the guide and
    # the reset tools exist only where the flow is reachable.
    def _api_tool_bindable(name: str) -> bool:
        if manifest_policy is None:
            return True
        return bool(getattr(api_tool_registry, "allows", lambda _name: True)(name))

    # The TingTing reset flow is deployment-wide, so its embedded guide goes in
    # regardless of project focus — the employee needs no project to reset a
    # password, and a guide the model never sees is one it will replace with an
    # invented hotline. One primary-key read per turn; absent port = absent block.
    if _api_tool_bindable("verify_tingting_identity"):
        configured_reader = getattr(deps.retrieval, "tingting_api_configured", None)
        if configured_reader is not None:
            try:
                tingting_configured = await configured_reader()
            except Exception as exc:  # noqa: BLE001 — a prompt gate must never break a turn
                logger.warning(
                    "tingting api configured-read failed error_type=%s", type(exc).__name__
                )
                tingting_configured = False
            if tingting_configured and tingting_reset_allowed:
                system += "\n\n" + tingting_api_prompt_block()
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
    elif compare_income_required_args is not None:
        allowed_tools = ("compare_income",)
    resolved_tool_registry = None
    if tingting_reset_allowed:
        # The support OA binds the reset flow ONLY: no project catalog, no
        # recruiting knowledge, no API tools beyond TingTing's. A low-confidence
        # route cannot widen this back to the full registry.
        allowed_tools = tuple(sorted(TINGTING_TOOL_NAMES))
    elif not tingting_reset_allowed:
        # The flow's tools are unreachable on this channel even if the route or a
        # low-confidence turn would otherwise expose the whole registry.
        if allowed_tools is not None:
            allowed_tools = tuple(name for name in allowed_tools if name not in TINGTING_TOOL_NAMES)
    if manifest_policy is not None:
        # Recruitment retains its proven prompt/routing path, but its bound
        # tools are still the manifest's immutable allowlist.  A low-confidence
        # route therefore cannot restore the full legacy registry.
        resolved_tool_registry = manifest_policy.tool_registry.names
        if tingting_reset_allowed:
            resolved_tool_registry = frozenset(resolved_tool_registry) & TINGTING_TOOL_NAMES
        else:
            resolved_tool_registry = frozenset(resolved_tool_registry) - TINGTING_TOOL_NAMES
        if allowed_tools is not None:
            allowed_tools = tuple(
                name for name in allowed_tools if name in resolved_tool_registry
            )
    if (
        required_authority_tool is not None
        and resolved_tool_registry is not None
        and required_authority_tool not in resolved_tool_registry
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
    employee_support = route.intent == "employee_support"
    if focused_rag:
        # An employee-support turn is a tool turn, never a knowledge-only turn:
        # keep the reset tools bound instead of collapsing to the project
        # knowledge authority, or the reset flow can never start.
        if employee_support:
            allowed_tools = tuple(
                name
                for name in (
                    "verify_tingting_identity",
                    "send_tingting_otp",
                    "confirm_tingting_otp",
                    "reset_tingting_password",
                    # Project knowledge rides along only when the turn is NOT the
                    # employee-support OA: that OA answers the reset flow and
                    # nothing else, so it never reaches the recruiting catalog.
                    *(("search_knowledge",) if not tingting_reset_allowed else ()),
                )
                if resolved_tool_registry is None or name in resolved_tool_registry
            )
        authority_tool = (
            None
            if employee_support
            else "list_active_jobs" if vacancy_catalog_required else "search_knowledge"
        )
        if (
            authority_tool is not None
            and resolved_tool_registry is not None
            and authority_tool not in resolved_tool_registry
        ):
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
        if authority_tool is not None:
            # Detailed Project answers use only the Project-owned category authority.
            # This also keeps legacy global timetable/project tools out of a focused turn.
            allowed_tools = (authority_tool,)
    # Model tier (Phase 5): low-complexity strategies use the fast model when one
    # is configured. ``should_use_fast_model`` encodes eligibility; the agent no-ops
    # the switch when no fast model was injected (tests / un-configured deployments).
    #
    # The metric must follow the client that actually serves the turn: prod ran
    # with no fast model configured while ``stage_timings.model_tier`` still read
    # "fast" on every low-complexity turn, which made the dashboard claim a tier
    # that never existed (34 turns/7d). Stamp "fast" only when the agent really
    # has one, so the metric can be trusted when tiering is turned on.
    fast_available = getattr(deps.agent, "fast_llm", None) is not None
    use_fast = fast_available and should_use_fast_model(route)
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
            # The runner's once-per-turn lead row (None for ports without the
            # resolve seam — those keep their own lookup inside context()).
            lead_ctx_kwargs = {"lead": lead_row} if lead_row is not None else {}
            lead_profile, lead_collection_question = await deps.lead.context(
                chat_id, user_text, recent_messages, contact_id=contact_id, **lead_ctx_kwargs
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
        _INCOME_COMPARE_HINT
        if compare_income_required_args is not None
        else routing_instruction(
            TurnRoute("recommend", "structured_lookup", reason="vacancy_listing")
        )
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
    }
    # ``forced_project_slug`` scopes the knowledge prefetch (and any project-keyed
    # tool); a focused project names its knowledge base exactly, so a turn never
    # has to ask which project a lookup belongs to.
    project_slug = getattr(project_context, "project_slug", None)
    if project_slug and (employee_support or (focused_rag and not vacancy_catalog_required)):
        agent_kwargs["forced_project_slug"] = project_slug
    if vacancy_catalog_required:
        agent_kwargs["required_tool"] = "list_active_jobs"
        required_args = _vacancy_required_args(decisions)
        agent_kwargs["required_tool_args"] = required_args
    elif compare_income_required_args is not None:
        agent_kwargs["required_tool"] = "compare_income"
        agent_kwargs["required_tool_args"] = compare_income_required_args
    elif focused_rag and not employee_support:
        agent_kwargs["required_tool"] = "search_knowledge"
        agent_kwargs["required_tool_args"] = {
            "query": evidence_query or user_text,
            "project_slug": project_context.project_slug,
        }
    if resolved_tool_registry is not None:
        agent_kwargs["resolved_tool_registry"] = resolved_tool_registry
    # Progressive delivery hooks ride only when the caller opened a stream: an
    # agent implementation (or test fake) that predates them is never asked for a
    # keyword it does not accept.
    if on_delta is not None:
        agent_kwargs["on_delta"] = on_delta
    if on_evidence is not None:
        agent_kwargs["on_evidence"] = on_evidence
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


class _LaneResolution(NamedTuple):
    """What one answer lane produced, consumed by the finalize/dispatch tail.

    ``terminal`` is set only when the lane itself stood the turn down (agent
    crash → ``_authority_gate``); run_turn returns it untouched and skips the
    finalize/dispatch tail.
    """

    lane: str
    candidate: str = ""
    generated: bool = False
    outcome_label: str = "sent"
    faq_metadata: dict | None = None
    terminal: TurnOutcome | None = None


async def _resolve_lane(
    *,
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    decisions: TurnDecisions,
    turn_route: TurnRoute,
    project_context,
    recent_messages: list[Any],
    manifest_policy,
    provider: str,
    recipient_id: str | None,
    timings: dict,
    trace_sink: DecisionTraceBuilder,
    started,
    lock_owner: str | None,
    status_task,
    t0: float,
    lead_row: dict | None = None,
    tingting_reset_allowed: bool = False,
    stream: _ProgressiveStream | None = None,
    agent_turn=None,
) -> _LaneResolution:
    """Select and run the turn's answer lane: clarification → direct → agent.

    ``timings['lane']`` and the decision trace record the winner exactly as
    before; ``faq_metadata`` is reserved for lane provenance metadata. Only
    the agent lane can fail — a crash stands the turn down through
    ``_authority_gate`` and surfaces as ``terminal``.

    ``agent_turn`` is the agent-lane callable, supplied by the composition point
    (``run_turn``) so this module never has to reach back into ``runner``. The
    default keeps a direct call working for any other caller.
    """
    if agent_turn is None:
        agent_turn = _agent_turn
    # Messenger leads are keyed by contact (NULL zalo_id), so the contact id is
    # the fallback key for the agent's lead context.
    contact_id = str(conv.contact_id) if getattr(conv, "contact_id", None) else None
    if project_context is not None and project_context.clarification:
        trace_sink.record_decision("context_selected", "project_clarification")
        trace_sink.record_decision("lane_selected", "project_clarification")
        timings["lane"] = "project_clarification"
        return _LaneResolution(
            lane="project_clarification",
            candidate=project_context.clarification,
            generated=False,
            outcome_label="project_clarification",
        )

    direct_context = project_context.direct_context if project_context is not None else None
    # The direct-context lane carries no tool calls, so it can never reach the
    # project's API: an employee-support turn must run on the agent lane.
    if (
        direct_context is not None
        and turn_route.reason != "vacancy_listing"
        and turn_route.intent != "employee_support"
    ):
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
        return _LaneResolution(
            lane="direct_context",
            candidate=raw,
            generated=True,
            outcome_label="direct_context",
        )

    # --- agent lane (runs to completion; NO hard cap) ---
    # The propagated deadline is advisory only — it bounds side lookups, never
    # the agent. Cancelling a live LLM call mid-generation produced excessive
    # TIMEOUT fallbacks in prod, so the agent is allowed to finish and its real
    # answer is sent. A genuinely hung provider call is reaped by the RQ
    # job_timeout backstop (>> any realistic turn) and the turn is recovered by
    # the reconcile sweep.
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
    try:
        agent_kwargs = {
            "provider": provider,
            "chat_id": recipient_id,
            "contact_id": contact_id,
            "recent_messages": recent_messages,
            "timings": timings,
            "decisions": decisions,
        }
        if project_context is not None:
            agent_kwargs["project_context"] = project_context
        if manifest_policy is not None:
            agent_kwargs["manifest_policy"] = manifest_policy
        if lead_row is not None:
            agent_kwargs["lead_row"] = lead_row
        agent_kwargs.update(
            _optional_policy_kwargs(
                agent_turn, {"tingting_reset_allowed": tingting_reset_allowed}
            )
        )
        if stream is not None:
            # Only the agent lane streams: the hooks are attached here so a
            # clarification/direct lane never opens a stream at all.
            agent_kwargs["on_delta"] = stream.push_delta
            agent_kwargs["on_evidence"] = stream.set_evidence
        raw = await agent_turn(
            state,
            deps,
            state.user_text,
            **_with_optional_trace(agent_turn, agent_kwargs, trace_sink),
        )
    except LLMThrottled as exc:
        # The worker owns the static degradation reply, but the
        # request-local trace would otherwise be lost at this boundary.
        # Transfer only the validated snapshot, never the live builder
        # or any prompt, exception, or tool payload.
        trace_sink.record_decision("degradation_reason", "llm_throttled")
        exc.decision_trace = trace_sink.snapshot_payload()
        raise  # let worker handle degradation msg (no LLM call)
    except Exception as exc:  # noqa: BLE001 — agent blew up -> stay silent
        # The bot could not produce an answer. An "internal error" text
        # is an engineer-facing detail, so the turn goes quiet: stop the
        # typing indicator, record the SUPPRESSED outcome (clears the
        # per-chat mutex), and let the structured log carry the failure.
        logger.error(
            "agent error, reply suppressed conversation=%s trace=%s: %s",
            state.conversation_id,
            state.trace_id or "-",
            exc,
        )
        trace_sink.record_decision("degradation_reason", "agent_error")
        # The agent path may have used deps.db (lead / system-prompt reads).
        # Clear any aborted transaction before the recovery reuses the
        # session for record_bot_outcome. Safe: record_bot_pending
        # already committed.
        try:
            await deps.db.rollback()
        except Exception:  # noqa: BLE001 — best-effort; worker_session also rolls back
            logger.debug("agent-error recovery rollback failed", exc_info=True)
        timings["total_ms"] = int(round((time.monotonic() - t0) * 1000))
        return _LaneResolution(
            lane="agent",
            terminal=await _authority_gate(
                state=state,
                deps=deps,
                conv=conv,
                svc=svc,
                reason="error",
                lock_owner=lock_owner,
                started=started,
                timings=timings,
                trace_sink=trace_sink,
                status_task=status_task,
                refresh_conv=True,
            ),
        )

    state.reply = raw
    return _LaneResolution(
        lane="agent",
        candidate=raw,
        generated=True,
        outcome_label="sent",
    )
