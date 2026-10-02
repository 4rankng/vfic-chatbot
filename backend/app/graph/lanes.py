"""Answer lanes: the agent lane and the route arguments it needs.

``_resolve_lane`` runs the agent lane and converts its crash into a stand-down
through the authority gate (the only lane that can fail). Everything a lane
needs to build its prompt — the tool allowlist, the forced
``required_tool_args`` for vacancy listing and income comparison, the ground
evidence query, the mandatory per-turn instruction — lives here rather than in
the turn entrypoint, so a routing change is a change to this module only.

``_agent_turn`` is injected into ``_resolve_lane`` by ``run_turn``: the
composition point stays in ``runner.py`` and this module keeps no back-reference
to it.
"""

from __future__ import annotations

import logging
import time
from inspect import Parameter, signature
from typing import Any, NamedTuple

from app.graph import absence_guard
from app.graph.answer_cache import (
    answer_cache_get,
    answer_cache_put,
    answer_project_scope,
    answer_scope,
    is_answer_cacheable,
    is_shareable_reply,
)
from app.graph.authority import _authority_gate
from app.graph.direct_context import (
    build_direct_system,
)
from app.graph.llm_semaphore import LLMThrottled
from app.graph.message_values import sender_is
from app.graph.ports import TurnDecisions
from app.shared.domain.vietnamese_gender import infer_gender_from_name
from app.graph.progressive import _ProgressiveStream
from app.graph.prompt_context import build_agent_user_text
from app.graph.router import (
    TurnRoute,
    _SUPPORT_CLARIFY_INTENTS,
    employee_support_route,
    requires_project_catalog,
    route_from_decisions,
    routing_instruction,
    should_use_fast_model,
)
from app.graph.runtime_policy import TINGTING_TOOL_NAMES
from app.graph.schemas import ROUTE_CONFIDENCE_FLOOR
from app.graph.tingting_guide import (
    TINGTING_RESET_REDIRECT_REPLY,
    tingting_hotline_reply,
    tingting_support_system_prompt,
)
from app.graph.types import BotRunState, GraphDeps, TurnOutcome
from app.recruitment.application.lead_lookup import (
    LeadLookup,
    UNRESOLVED_LEAD,
    UnresolvedLead,
)
from app.recruitment.domain.recommendation import (
    is_salary_profile_statement,
    parse_salary_band,
)
from app.shared.domain.addressing import address_form
from app.shared.domain.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)
DIRECT_HISTORY_TOKEN_BUDGET = 12_000
_INCOME_COMPARE_HINT = (
    "Ý định: hỏi mốc thu nhập chung khi chưa chốt dự án. Phải dùng compare_income trước, "
    "trả lời theo từng dự án bằng đúng cơ sở dữ liệu (thu nhập tháng, bình quân năm chia 12, "
    "thưởng, kỳ lương), không gộp các cơ sở tính thành một con số duy nhất."
)

# The support OA itself serves the reset flow only. Operator rule (2026-09-29):
# no human works this OA, so nothing here queues one — every would-be
# escalation returns the fixed hotline reply instead (tingting_guide.py). The
# reply is the whole handoff; there is no queue write to keep honest.
#
# This and the support-OA hotline reply in ``_agent_turn`` are the ONLY two
# candidate-facing code-authored replies in the turn path (operator-approved
# verbatim strings, 2026-09-29). Every other reply is authored by the LLM agent;
# an off-scope turn is refused by the model under the routing instruction.


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


def _tingting_account_conversation(conv) -> bool:
    """Whether the conversation sits on the TingTing support OA (identity only).

    Deliberately pin-free, unlike :func:`_tingting_reset_allowed`: the OA's
    prompt scope is a property of the channel identity, so the account keeps the
    support prompt even while the reset link is unconfigured — a pin-gated
    prompt branch would fall through to the recruitment preamble (project
    directory, advertising rules) on exactly that fallback path.
    """
    from app.channels.types import TINGTING_OA_ACCOUNT_KEY

    identity = getattr(conv, "channel_identity", None)
    if identity is None or str(getattr(identity, "provider", "") or "") != "zalo_oa":
        return False
    return str(getattr(identity, "account_key", "") or "") == TINGTING_OA_ACCOUNT_KEY


async def _tingting_hotline(deps: GraphDeps) -> str:
    """The admin-editable escalation hotline, read at turn time (``""`` = unset).

    Best-effort like every other settings read: a failure must never break the
    turn, and the reply builders degrade to the honest no-number form rather
    than resurrecting a number from code. Read only on support-OA turns; the
    empty read is flagged by the repository reader.
    """
    reader = getattr(deps.retrieval, "tingting_hotline", None)
    if reader is None:
        return ""
    try:
        return str(await reader() or "").strip()
    except Exception as exc:  # noqa: BLE001 — a settings read must never break a turn
        logger.warning("tingting hotline read failed error_type=%s", type(exc).__name__)
        return ""


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
        **agent_kwargs,
    )


async def _tingting_addressing(state: BotRunState, deps: GraphDeps) -> str:
    """Gendered pronoun instruction from the lead's own Zalo display name.

    The support persona stays neutral ("anh/chị") unless a name carries an
    unambiguous Vietnamese marker (2026-09-28: "Trần Quang Việt" was addressed
    neutrally because the name lives on the contact record — the employee never
    typed it in-chat and the blocked sends deferred enrichment). Best-effort:
    any failure keeps the neutral default. The name itself NEVER enters the
    prompt — only the pronoun — so the bot cannot greet the employee by their
    record name (the reset guide's privacy rule).
    """
    try:
        conv = await deps.conversation.get(state.conversation_id)
        name = str(getattr(getattr(conv, "contact", None), "display_name", "") or "")
        gender = infer_gender_from_name(name)
        if not gender:
            return ""
        pronoun = "anh" if gender == "male" else "chị"
        return (
            "\n\n=== XƯNG HÔ ===\nDựa trên tên Zalo của người nhắn: gọi họ là "
            f'"{pronoun}" thay vì "anh/chị" trong mọi tin nhắn. KHÔNG gọi tên họ.'
        )
    except Exception as exc:  # noqa: BLE001 — addressing is best-effort, never breaks a turn
        logger.warning(
            "tingting addressing inference failed error_type=%s", type(exc).__name__
        )
        return ""


async def _compose_reply_without_tools(
    deps: GraphDeps,
    user_text: str,
    *,
    system: str,
    metrics: dict | None,
) -> str:
    """One tool-free agent round the model authors; ``""`` suppresses the turn.

    Replaces the removed ``AgentModel.direct`` seam: the agent lane is the only
    model entrypoint, so a route that cannot reach its authority tool asks the
    model for an honest answer with no tools bound rather than shipping a
    code-authored line. An empty generation suppresses instead of inventing one.
    """
    reply = await deps.agent.agent(
        user_text,
        **{
            "system": system,
            "retrieval": deps.retrieval,
            "embedder": deps.embedder,
            "allowed_tools": None,
            # Empty registry: ``filter_tool_schemas`` then returns no tools,
            # so this round cannot re-enter a tool loop.
            "resolved_tool_registry": frozenset(),
            "metrics": metrics,
        },
    )
    return reply or ""


async def _absence_self_check(
    *,
    deps: GraphDeps,
    reply: str,
    route: TurnRoute,
    agent_kwargs: dict,
    timings: dict,
    system: str,
    user_text: str,
    chat_id: str,
    recent_messages: list[Any],
    lead_profile: str,
    lead_collection_instruction: str,
    tingting_reset_allowed: bool,
    tingting_support_account: bool,
) -> str:
    """Verify an unevidenced project absence against the catalog before sending.

    A reply asserting "chưa có dự án ..." on a turn that never ran
    ``list_active_projects`` can ship a confident false negative: the catalog
    card may not match the place, the KB search may miss it, and nothing
    re-checks the claim. One forced self-check re-runs the agent with the
    catalog required (an unscoped knowledge search allowed beside it); a check
    that still finds nothing ships the instructed hedge + hotline instead. At
    most one retry, never a loop, and the stored conversation focus is never
    touched.
    """
    if (
        timings is None
        or not absence_guard.enabled()
        or route.intent not in absence_guard.GUARD_INTENTS
        or tingting_reset_allowed
        or tingting_support_account
        or not absence_guard.reply_asserts_place_absence(reply)
        or absence_guard.catalog_evidence_this_turn(timings)
    ):
        return reply
    hotline = await _tingting_hotline(deps)

    def _retry_text(route_hint: str) -> str:
        return build_agent_user_text(
            chat_id=chat_id,
            current_user_text=user_text,
            recent_messages=recent_messages,
            lead_profile=lead_profile,
            lead_collection_instruction=lead_collection_instruction,
            route_hint=route_hint,
        )

    registry = agent_kwargs.get("resolved_tool_registry")
    if registry is not None and "list_active_projects" not in registry:
        # The turn's registry cannot reach the catalog: one tool-free round
        # writes the honest hedge (the model authors every reply; an empty
        # generation suppresses the turn instead of shipping the false claim).
        reply = await _compose_reply_without_tools(
            deps,
            _retry_text(absence_guard.hedge_route_hint(hotline)),
            system=system,
            metrics=timings,
        )
        if (reply or "").strip():
            timings["absence_guard"] = "hedged"
            return reply
        timings["absence_guard"] = "retry_suppressed"
        return ""
    retry_reply = await deps.agent.agent(
        _retry_text(absence_guard.retry_route_hint(hotline)),
        **absence_guard.build_retry_kwargs(agent_kwargs),
    )
    if not (retry_reply or "").strip():
        timings["absence_guard"] = "retry_suppressed"
        return ""
    timings["absence_guard"] = (
        "hedged"
        if absence_guard.reply_asserts_place_absence(retry_reply)
        or absence_guard.is_hedge_form(retry_reply)
        else "retry_verified"
    )
    return retry_reply


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
    manifest_policy=None,
    project_context=None,
    decisions: TurnDecisions | None = None,
    lead_row: LeadLookup = UNRESOLVED_LEAD,
    tingting_reset_allowed: bool = False,
    tingting_support_account: bool = False,
    mandatory_instruction: str = "",
    on_delta=None,
    on_evidence=None,
) -> str:
    # Keep a completed miss distinct from an omitted prefetch. The prompt adapter
    # must reuse the runner's lookup even before a candidate has a lead row.
    lead_ctx_kwargs = {} if isinstance(lead_row, UnresolvedLead) else {"lead": lead_row}
    lead_row = None if isinstance(lead_row, UnresolvedLead) else lead_row
    # Normalize once: every downstream consumer (vacancy args, evidence query,
    # forced-tool args) assumes a TurnDecisions; a None fan-out (degraded runs)
    # previously crashed on ``decisions.recent_vacancy`` instead of degrading.
    decisions = decisions or TurnDecisions(degraded=True)
    route = route_from_decisions(user_text, decisions)
    if route.intent == "employee_support" and not tingting_reset_allowed:
        # Employee-account support belongs to the TingTing OA: elsewhere the turn
        # is answered with the operator's exact pointer to that OA instead of
        # running a flow this channel cannot serve (the guide and the reset tools
        # are not bound here either).
        return TINGTING_RESET_REDIRECT_REPLY
    if tingting_reset_allowed and route.intent != "employee_support":
        # This IS the support OA. It serves the reset flow and no recruitment
        # knowledge, but "the employee wants help here and has not said what"
        # (``general``/``small_talk``, Jev degraded, or a reading below the route
        # floor) is not a reason to call a person: the bot asks the fixed confirm
        # question (Anh/chị cần đặt lại mật khẩu ứng dụng TingTing phải không ạ?)
        # and the answer decides — a named problem runs the reset flow
        # (``employee_support`` on the next turn), anything else lands in the
        # handoff branch below. Only a confident non-support intent (a
        # recruitment/admin question) goes straight to a human.
        if route.intent in _SUPPORT_CLARIFY_INTENTS or route.confidence < ROUTE_CONFIDENCE_FLOOR:
            route = employee_support_route(
                reason="employee_support_clarify",
                confidence=max(route.confidence, ROUTE_CONFIDENCE_FLOOR),
            )
        else:
            return tingting_hotline_reply(await _tingting_hotline(deps))
    focused_project = bool(
        project_context is not None and getattr(project_context, "state", None) == "FOCUSED"
    )
    evidence_query = _vacancy_evidence_query(
        user_text,
        decisions,
        recent_messages,
        focused_project=focused_project,
    )
    vacancy_catalog_required = requires_project_catalog(route, decisions)
    compare_income_required_args = _compare_income_required_args(
        user_text,
        route_intent=route.intent,
        project_context=project_context,
    )
    if tingting_reset_allowed:
        # The OA has no catalog and no income tool: a stale Jev vacancy flag must
        # not force `list_active_projects` onto a turn whose only bound tools are the
        # reset ones.
        vacancy_catalog_required = False
        compare_income_required_args = None
    required_authority_tool = (
        "list_active_projects"
        if vacancy_catalog_required
        else "compare_income" if compare_income_required_args is not None else None
    )
    if manifest_policy is not None and manifest_policy.pack_key != "recruitment":
        allowed_tools = (
            route.tools if route.confidence >= ROUTE_CONFIDENCE_FLOOR else None
        )
        if vacancy_catalog_required:
            allowed_tools = ("list_active_projects",)
        elif compare_income_required_args is not None:
            allowed_tools = ("compare_income",)
        if allowed_tools is not None:
            allowed_tools = tuple(
                name for name in allowed_tools if name in manifest_policy.tool_registry.names
            )
        if required_authority_tool is not None and not manifest_policy.tool_registry.allows(
            required_authority_tool
        ):
            return await _compose_reply_without_tools(
                deps,
                user_text,
                system=(
                    "Bạn là tư vấn viên tuyển dụng. Công cụ dữ liệu cần thiết hiện không khả dụng. "
                    "Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể kiểm tra thông tin, không "
                    "khẳng định có việc và không bịa dữ liệu."
                ),
                metrics=timings,
            )
        composed = await run_manifest_composed_agent(
            user_text,
            deps,
            policy=manifest_policy,
            allowed_tools=allowed_tools,
            lookup_query=evidence_query or user_text,
            required_tool=(
                "list_active_projects"
                if vacancy_catalog_required
                else "compare_income" if compare_income_required_args is not None else None
            ),
            # The model composes the vacancy criteria args from the conversation;
            # the tool ranks the whole catalog against whatever the candidate stated.
            required_tool_args=(
                None if vacancy_catalog_required else compare_income_required_args
            ),
            metrics=timings,
        )
        if composed is not None:
            return composed
        # The manifest policy deactivated mid-turn (the resolve bailed) — a race,
        # not a normal path. Suppress: there is no agent-composed reply to send
        # and the turn must never fall back to a code-authored line.
        return ""

    # System prompt = active persona + master index of active products (best-effort;
    # collapses to AGENT_SYSTEM_PROMPT on any failure so a turn never breaks).
    # Redis-cached (10min TTL, version-bumped on persona/project edits) so a hit
    # is sub-ms; a miss does 2 DB reads (persona + active-product index). Timed
    # separately so the dashboard can attribute it rather than hiding it inside
    # the (post-preamble) total_ms slice.
    from app.graph.context import build_system_prompt

    sys_t0 = time.monotonic()
    if tingting_reset_allowed or tingting_support_account:
        # The support OA is not a recruitment channel: its prompt is the code
        # persona (+ the reset guide when the key is configured), never the
        # recruitment persona, the project index, or the recruiting rules. The
        # identity check owns this branch alongside the pin-gated reset flag so
        # an unconfigured reset link cannot leak the recruitment preamble
        # (project directory, advertising rules) onto the support account.
        configured_reader = getattr(deps.retrieval, "tingting_api_configured", None)
        tingting_configured = False
        if configured_reader is not None:
            try:
                tingting_configured = bool(await configured_reader())
            except Exception as exc:  # noqa: BLE001 — a prompt gate must never break a turn
                logger.warning(
                    "tingting api configured-read failed error_type=%s", type(exc).__name__
                )
        system = tingting_support_system_prompt(
            include_guide=tingting_configured,
            hotline=await _tingting_hotline(deps),
        )
        addressing = await _tingting_addressing(state, deps)
        if addressing:
            system += addressing
        sys_prompt_hit = False
    else:
        system, sys_prompt_hit = await build_system_prompt(
            deps.retrieval,
            provider=provider,
        )
    if (
        project_context is not None
        and not tingting_reset_allowed
        and not tingting_support_account
    ):
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
                "để giới thiệu lựa chọn phù hợp; không tải kiến thức chi tiết của mọi dự án. "
                "Khi ứng viên yêu cầu tất cả/toàn bộ danh sách, phải nêu đủ từng dự án trong "
                "kết quả list_active_projects của phạm vi hiện tại, mỗi dự án đúng một lần; "
                "không rút thành một nhóm nhỏ rồi yêu cầu hỏi thêm."
            )

    # The retired direct-context lane is folded into this agent lane: when the
    # focused project's KB is in DIRECT_CONTEXT mode its full text rides in the
    # prompt and the turn runs tool-free (a tool cannot add evidence the KB
    # already carries). The same route exclusions the old lane used apply.
    direct_context = (
        getattr(project_context, "direct_context", None)
        if project_context is not None
        else None
    )
    direct_context_turn = (
        direct_context is not None
        and required_authority_tool is None
        and route.intent != "employee_support"
        and route.intent != "out_of_scope"
        and not tingting_reset_allowed
        and not tingting_support_account
    )
    if direct_context_turn and direct_context is not None:
        system += (
            "\n\n=== KIẾN THỨC DỰ ÁN (toàn văn, nguồn chính thức) ===\n"
            f"{build_direct_system(direct_context)}"
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
        timings.setdefault("route_reason", route.reason)
        timings.setdefault("route_confidence", round(route.confidence, 2))
    # Hard tool-gate: a confident route constrains which tools the LLM may call.
    # Low-confidence routes fall through to the full toolset (filter_tool_schemas
    # returns the whole registry when allowed is empty/None).
    allowed_tools = route.tools if route.confidence >= ROUTE_CONFIDENCE_FLOOR else None
    if vacancy_catalog_required:
        allowed_tools = ("list_active_projects",)
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
        return await _compose_reply_without_tools(
            deps,
            user_text,
            system=(
                "Bạn là tư vấn viên tuyển dụng. Công cụ dữ liệu cần thiết hiện không khả dụng. "
                "Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa thể kiểm tra thông tin, không "
                "khẳng định có việc và không bịa dữ liệu."
            ),
            metrics=timings,
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
            else required_authority_tool or "search_knowledge"
        )
        if (
            authority_tool is not None
            and resolved_tool_registry is not None
            and authority_tool not in resolved_tool_registry
        ):
            return await _compose_reply_without_tools(
                deps,
                user_text,
                system=(
                    f"{system}\n\n"
                    "Bạn là tư vấn viên tuyển dụng. Dữ liệu của dự án hiện không thể tra cứu. "
                    "Hãy trả lời tự nhiên bằng tiếng Việt rằng chưa có thông tin đã xác minh, "
                    "không khẳng định có việc và không bịa dữ liệu."
                ),
                metrics=timings,
            )
        if authority_tool is not None:
            # Detailed Project answers use only the Project-owned category authority.
            # This also keeps legacy global timetable/project tools out of a focused turn.
            allowed_tools = (authority_tool,)
    if direct_context_turn:
        # The KB text is already in the prompt, so a tool cannot add evidence:
        # run the turn tool-free (the retired direct-context lane's behaviour)
        # with the agent authoring the prose.
        allowed_tools = None
        resolved_tool_registry = frozenset()
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
    allow_lead_context = not tingting_reset_allowed and (
        manifest_policy is None
        or (
            manifest_policy.pack_key == "recruitment"
            and "candidate_intake" in manifest_policy.capability_ids
        )
    )
    lead_port = deps.lead
    if allow_lead_context and lead_port is not None:
        try:
            lead_profile, lead_collection_question = await lead_port.context(
                chat_id, user_text, recent_messages, contact_id=contact_id, **lead_ctx_kwargs
            )
            if lead_collection_question:
                lead_collection_instruction = lead_port.instruction(lead_collection_question)
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

    # Answer cache (read): a repeated question about stateless Project
    # information is answered from the reply a previous turn already sent, with
    # no model call. Eligibility and the scope token are the same ones the write
    # below uses, so a turn that may be read is exactly a turn that may be
    # written.
    answer_scope_token = ""
    prior_messages = recent_messages
    if (
        prior_messages
        and sender_is(prior_messages[-1], "WORKER")
        and (getattr(prior_messages[-1], "body", "") or "").strip() == user_text.strip()
    ):
        prior_messages = prior_messages[:-1]
    if is_answer_cacheable(
        allowed_tools=allowed_tools,
        tingting_reset_allowed=tingting_reset_allowed,
        tingting_support_account=tingting_support_account,
        has_conversation_history=bool(prior_messages),
        user_text=user_text,
    ):
        project_scope = await answer_project_scope(
            deps.retrieval, getattr(project_context, "project_slug", None)
        )
        if project_scope:
            answer_scope_token = await answer_scope(
                project_scope=project_scope,
                address=address_form((lead_row or {}).get("gender")),
                intake_context=f"{lead_profile}\n{lead_collection_instruction}",
                provider=provider,
            )
            cache_t0 = time.monotonic()
            cached = await answer_cache_get(
                user_text, embedder=deps.embedder, scope=answer_scope_token
            )
            if timings is not None:
                timings["answer_cache_lookup_ms"] = int(
                    round((time.monotonic() - cache_t0) * 1000)
                )
                timings["answer_cache"] = (
                    {"hit": True, "tier": cached.tier, "similarity": round(cached.similarity, 3)}
                    if cached is not None
                    else {"hit": False}
                )
            if cached is not None:
                return cached.result

    route_hint = (
        mandatory_instruction
        if mandatory_instruction
        else _INCOME_COMPARE_HINT
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
        # Server-side conversation identity for tools that count per-conversation
        # state (the TingTing verification cap). Never model-supplied: scoped_args
        # injects it into the tool args at dispatch time.
        "conversation_scope": str(getattr(state, "conversation_id", "") or ""),
    }
    # ``forced_project_slug`` scopes the knowledge prefetch (and any project-keyed
    # tool); a focused project names its knowledge base exactly, so a turn never
    # has to ask which project a lookup belongs to.
    project_slug = getattr(project_context, "project_slug", None)
    if project_slug and not tingting_reset_allowed and (
        employee_support or (focused_rag and not vacancy_catalog_required)
    ):
        agent_kwargs["forced_project_slug"] = project_slug
    if vacancy_catalog_required:
        agent_kwargs["required_tool"] = "list_active_projects"
        # No forced args: the model composes the criteria from the conversation.
        agent_kwargs["required_tool_args"] = None
    elif compare_income_required_args is not None:
        agent_kwargs["required_tool"] = "compare_income"
        agent_kwargs["required_tool_args"] = compare_income_required_args
    elif focused_rag and not employee_support:
        agent_kwargs["required_tool"] = "search_knowledge"
        agent_kwargs["required_tool_args"] = {
            "query": evidence_query or user_text,
            "project_slug": getattr(project_context, "project_slug", None),
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
        **agent_kwargs,
    )
    reply = await _absence_self_check(
        deps=deps,
        reply=reply,
        route=route,
        agent_kwargs=agent_kwargs,
        timings=timings,
        system=system,
        user_text=user_text,
        chat_id=chat_id,
        recent_messages=recent_messages,
        lead_profile=lead_profile,
        lead_collection_instruction=lead_collection_instruction,
        tingting_reset_allowed=tingting_reset_allowed,
        tingting_support_account=tingting_support_account,
    )
    if timings is not None:
        timings["tools_invoked"] = sorted(
            set(timings.get("tool_call_counts") or {})
            | set(timings.get("prefetch_tool_names") or ())
        )
    # Answer cache (write): only a turn that serves stateless Project
    # information and whose reply was built from tool evidence depends on the
    # question alone. Two evidence signals are accepted because only the
    # knowledge/timetable/income/faq lanes run a routed prefetch: the catalog
    # lane has no prefetch branch, so the model calls its tool itself and
    # ``tool_calls`` is what proves the reply was grounded. A no-evidence reply
    # ("không tìm thấy") is refused again by ``is_shareable_reply``, and an
    # absent timing sink (direct calls, stub agents) disables the write.
    if answer_scope_token and timings is not None:
        grounded = timings.get("prefetch_hit") is True or int(timings.get("tool_calls") or 0) > 0
        if grounded and is_shareable_reply(reply, lead_row=lead_row):
            await answer_cache_put(
                user_text, reply, embedder=deps.embedder, scope=answer_scope_token
            )
            timings["answer_cache"]["stored"] = True
    return reply


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
    started,
    lock_owner: str | None,
    status_task,
    t0: float,
    lead_row: LeadLookup = UNRESOLVED_LEAD,
    tingting_reset_allowed: bool = False,
    stream: _ProgressiveStream | None = None,
    agent_turn=None,
) -> _LaneResolution:
    """Select and run the turn's answer lane: the agent authors every reply.

    ``timings['lane']`` records the winner; ``faq_metadata``
    is reserved for lane provenance metadata. Only the agent lane can fail — a
    crash stands the turn down through ``_authority_gate`` and surfaces as
    ``terminal``.

    ``agent_turn`` is the agent-lane callable, supplied by the composition point
    (``run_turn``) so this module never has to reach back into ``runner``. The
    default keeps a direct call working for any other caller.
    """
    if agent_turn is None:
        agent_turn = _agent_turn
    # Messenger leads are keyed by contact (NULL zalo_id), so the contact id is
    # the fallback key for the agent's lead context.
    contact_id = str(conv.contact_id) if getattr(conv, "contact_id", None) else None
    # The support OA never touches recruitment machinery: this identity flag
    # (pin-free, unlike tingting_reset_allowed) gates the recruitment prompt
    # branch and rides along to the agent's prompt branch.
    tingting_support_account = _tingting_account_conversation(conv)
    # A message that matches several projects is ambiguous: the retired
    # clarification lane returned a code-built question. The agent now authors
    # that question, driven by a mandatory instruction that wins the route hint.
    mandatory_instruction = ""
    if (
        project_context is not None
        and project_context.clarification
        and not tingting_reset_allowed
        and not tingting_support_account
        and turn_route.intent != "out_of_scope"
    ):
        names = tuple(getattr(project_context, "clarification_projects", ()) or ())
        if not names:
            names = (project_context.clarification,)
        mandatory_instruction = (
            "NGỮ CẢNH BẮT BUỘC: tin nhắn của ứng viên khớp "
            f"{len(names)} dự án. PHẢI hỏi lại ứng viên muốn hỏi dự án nào trước khi trả lời; "
            "KHÔNG trả lời bằng dữ liệu của một dự án, KHÔNG đoán. "
            "Danh sách: " + ", ".join(names)
        )

    # --- agent lane (runs to completion; NO hard cap) ---
    # The propagated deadline is advisory only — it bounds side lookups, never
    # the agent. Cancelling a live LLM call mid-generation produced excessive
    # TIMEOUT fallbacks in prod, so the agent is allowed to finish and its real
    # answer is sent. A genuinely hung provider call is reaped by the RQ
    # job_timeout backstop (>> any realistic turn) and the turn is recovered by
    # the reconcile sweep.
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
        if not isinstance(lead_row, UnresolvedLead):
            agent_kwargs["lead_row"] = lead_row
        agent_kwargs.update(
            _optional_policy_kwargs(
                agent_turn,
                {
                    "tingting_reset_allowed": tingting_reset_allowed,
                    "tingting_support_account": tingting_support_account,
                    "mandatory_instruction": mandatory_instruction,
                },
            )
        )
        if stream is not None:
            stream.defer_catalog = not tingting_reset_allowed and requires_project_catalog(
                turn_route, decisions
            )
            # Only the agent lane streams: the hooks are attached here so a
            # clarification/direct lane never opens a stream at all.
            agent_kwargs["on_delta"] = stream.push_delta
            agent_kwargs["on_evidence"] = stream.set_evidence
        raw = await agent_turn(
            state,
            deps,
            state.user_text,
            **agent_kwargs,
        )
    except LLMThrottled:
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
