"""The bot-turn pipeline (mirrors the LangGraph topology 1:1; node-named functions).

    load_conversation_state -> typing -> agent
      agent (error) -> error_reply
      agent (ok)    -> finalize_user_visible_reply
      finalize_user_visible_reply -> pre_send_guard -> ownership_ok?
                                yes -> dispatch_claimed_message -> record_bot_outcome
                                no  -> log_suppressed

This module is the composition point and nothing else: ``run_turn`` is the one
end-to-end entrypoint, and each stage it drives lives in the module that owns
that concern —

- ``graph/progressive.py`` — the progressive stream, the early-bubble sender, and
  the delivered-bubble record every terminal path must honour.
- ``graph/dispatch.py`` — the typing heartbeat, the pre-send guard, and the
  atomic claim → send → record unit.
- ``graph/lanes.py`` — clarification / direct-context / agent routing and the
  route argument builders.
- ``graph/authority.py`` — the stand-down exit and the outcome it records.
- ``graph/telemetry.py`` — the shared per-stage timing accumulator.

The stages were extracted out of this file without behavioural change, so the
names below stay re-exported here: the worker, the web-chat endpoint, the
outbound crash guard, and the characterization tests all import them from
``app.graph.runner``.

The reply boundary is ``_finalize_user_visible_reply`` -> ``strip_provider_artifacts``
(``graph/think_strip.py``): the answer is shipped exactly as the agent generated it —
the only transformation is dropping an inline provider thinking block so it never
reaches the candidate. The former answer-review layer (regex cleaning,
truncation, empty-reply verdicts, the ``safety_verdict`` trace) and the LLM
safety judge before it were removed outright: neither is an LLM call, both sat
between the generated answer and the send. Keep the diagram honest so a latency
investigation does not hunt for a node that does not exist.

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

from app.core.config import get_settings
from app.graph.authority import _authority_gate, _record_silent_terminal
from app.graph.dispatch import (
    _build_outbox_payload,
    _cancel_status_task,
    _channel_for_conversation,
    _claim_and_dispatch,
    _delivery_status_for_send_error,
    _delivery_statuses,
    _dispatch_claimed_message,
    _finalize_user_visible_reply,
    _OWNERSHIP_REFRESH_COLUMNS,
    _recipient_for_conversation,
    _record_dispatched_outcome,
    _status_heartbeat,
)
from app.graph.lanes import (
    _agent_turn,
    _compare_income_required_args,
    _optional_policy_kwargs,
    _resolve_lane,
    _tingting_reset_allowed,
    _vacancy_evidence_query,
    DIRECT_HISTORY_TOKEN_BUDGET,
    run_manifest_composed_agent,
    tingting_hotline_reply,
)
from app.graph.ports import TurnDecisions
from app.graph.progressive import (
    _await_first_bubble,
    _bubble_has_substance,
    _complete_progressive_prefix,
    _contact_evidence_text,
    _EarlyBubble,
    _next_sendable_offset,
    _note_delivered_bubble,
    _progressive_send_enabled,
    _ProgressiveStream,
    delivered_bubble,
    delivered_bubble_payload,
    DeliveredBubble,
    finalize_delivered_bubble,
    PROGRESSIVE_BUBBLE_MIN_CHARS,
    PROGRESSIVE_MAX_WAIT_CHARS,
    PROGRESSIVE_SUBSTANCE_MIN_CHARS,
)
from app.graph.router import route_from_decisions
from app.graph.tingting_guide import TINGTING_RESET_REDIRECT_REPLY
from app.graph.telemetry import (
    _stamp_db,
    _stamp_end_to_end,
    _stamp_outbound_telemetry,
)
from app.graph.types import BotRunState, GraphDeps, TurnOutcome, _now
from app.recruitment.application.lead_lookup import LeadLookup, UNRESOLVED_LEAD
from app.recruitment.domain.provider import provider_from_conversation

logger = logging.getLogger(__name__)
RECENT_HISTORY_LIMIT = 16
OA_PROFILE_LOOKUP_TIMEOUT_SECONDS = 2.0
# A wrong "anh"/"chị" reads worse to the candidate than staying neutral, so an
# inferred gender is stored only at or above this confidence; anything lower (and
# an explicit "unknown") is left for the candidate's next message to re-judge.
GENDER_INFERENCE_MIN_CONFIDENCE = 0.7
_INFERRED_GENDERS = frozenset({"male", "female"})

__all__ = [
    "BotRunState",
    "DeliveredBubble",
    "DIRECT_HISTORY_TOKEN_BUDGET",
    "GENDER_INFERENCE_MIN_CONFIDENCE",
    "GraphDeps",
    "OA_PROFILE_LOOKUP_TIMEOUT_SECONDS",
    "PROGRESSIVE_BUBBLE_MIN_CHARS",
    "PROGRESSIVE_MAX_WAIT_CHARS",
    "PROGRESSIVE_SUBSTANCE_MIN_CHARS",
    "RECENT_HISTORY_LIMIT",
    "TINGTING_RESET_REDIRECT_REPLY",
    "tingting_hotline_reply",
    "TurnDecisions",
    "TurnOutcome",
    "_EarlyBubble",
    "_ProgressiveStream",
    "_agent_turn",
    "_authority_gate",
    "_await_first_bubble",
    "_bubble_has_substance",
    "_build_outbox_payload",
    "_cancel_status_task",
    "_claim_and_dispatch",
    "_compare_income_required_args",
    "_complete_progressive_prefix",
    "_contact_display_name",
    "_contact_evidence_text",
    "_delivery_status_for_send_error",
    "_delivery_statuses",
    "_dispatch_claimed_message",
    "_finalize_user_visible_reply",
    "_next_sendable_offset",
    "_note_delivered_bubble",
    "_optional_policy_kwargs",
    "_OWNERSHIP_REFRESH_COLUMNS",
    "_progressive_send_enabled",
    "_recipient_for_conversation",
    "_record_dispatched_outcome",
    "_record_silent_terminal",
    "_resolve_lane",
    "_stamp_db",
    "_stamp_end_to_end",
    "_stamp_outbound_telemetry",
    "_tingting_reset_allowed",
    "_vacancy_evidence_query",
    "_zalo_for_conversation",
    "delivered_bubble",
    "delivered_bubble_payload",
    "finalize_delivered_bubble",
    "provider_from_conversation",
    "run_manifest_composed_agent",
    "run_turn",
]


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


def _contact_display_name(conv) -> str:
    """Stored provider profile label for the candidate (Messenger/OA), "" when absent."""
    contact = getattr(conv, "contact", None)
    return str(getattr(contact, "display_name", "") or "").strip()


async def run_turn(state: BotRunState, deps: GraphDeps) -> TurnOutcome:
    """Own setup status across the initial gates and the complete graph turn."""
    preamble_status_task = deps.preamble_status_task
    deps.preamble_status_task = None
    try:
        return await _run_turn(state, deps, preamble_status_task=preamble_status_task)
    finally:
        await _cancel_status_task(preamble_status_task)


async def _run_turn(
    state: BotRunState,
    deps: GraphDeps,
    *,
    preamble_status_task: asyncio.Task[None] | None,
) -> TurnOutcome:
    """Execute one bot turn end-to-end and persist the SENT/SUPPRESSED outcome.

    Reads top-to-bottom as gate → lane → finalize → dispatch: authority/lock
    gates, one answer lane (see ``lanes._resolve_lane``), the converged
    reply-policy boundary, then the atomic claim/dispatch unit
    (``dispatch._claim_and_dispatch``). Every stand-down funnels through
    ``authority._authority_gate``.
    """
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
    manifest_policy = None
    if deps.runtime_policy is None:
        # Without a policy port a stamped turn cannot prove its authority
        # against anything; the gate below is the fail-closed exit.
        if has_runtime_stamp:
            return await _authority_gate(
                state=state,
                deps=deps,
                conv=conv,
                svc=svc,
                reason="stale_runtime_authority",
                lock_owner=lock_owner,
                status_task=preamble_status_task,
            )
    elif has_runtime_stamp:
        # One resolution serves the whole turn. The fingerprint checksum
        # covers the complete authority payload (revision, generation,
        # pinned artifacts, KB vector), so matching it against the turn's
        # stamp subsumes the stamp-currency check without a second full
        # derivation of the installation.
        manifest_policy = await deps.runtime_policy.resolve_active_policy()
        if manifest_policy is None or not (
            manifest_policy.revision_id == state.runtime_revision_id
            and manifest_policy.fingerprint_checksum == state.runtime_fingerprint
        ):
            return await _authority_gate(
                state=state,
                deps=deps,
                conv=conv,
                svc=svc,
                reason="stale_runtime_authority",
                lock_owner=lock_owner,
                status_task=preamble_status_task,
            )
    elif await deps.runtime_policy.resolve_active_policy() is not None:
        # A clean cutover never lets pre-authority jobs inherit today's
        # capabilities.  Tests and explicitly legacy deployments inject no
        # runtime policy and retain their existing behavior.
        return await _authority_gate(
            state=state,
            deps=deps,
            conv=conv,
            svc=svc,
            reason="missing_runtime_authority",
            lock_owner=lock_owner,
            status_task=preamble_status_task,
        )
    if lock_owner:
        db_t0 = time.monotonic()
        await deps.db.refresh(conv, _OWNERSHIP_REFRESH_COLUMNS)
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
        from app.channels.types import oa_user_id

        user_id = oa_user_id(conv.zalo_chat_id)
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
    # Setup pulses cover conversation/runtime/ownership resolution. Drain that
    # request before the account-bound sender takes over, so loops never overlap.
    await _cancel_status_task(preamble_status_task)

    # Active-status heartbeat: native typing pulses while the turn processes.
    # Started right after the sender is resolved (before last_messages / pending)
    # so the indicator appears as early as possible. Cancelled before every real
    # send so the indicator stops on the answer.
    recipient_id = _recipient_for_conversation(conv)
    status_task = (
        asyncio.create_task(_status_heartbeat(zalo, recipient_id, settings=settings))
        if _channel_for_conversation(conv) == "zalo_bot" and recipient_id
        else None
    )
    jev_task: asyncio.Task[TurnDecisions] | None = None
    lane_task: asyncio.Task | None = None
    try:
        db_t0 = time.monotonic()
        recent_messages = await svc.last_messages(conv, limit=RECENT_HISTORY_LIMIT)
        _stamp_db(timings, "last_messages", db_t0)
        contact_evidence = _contact_evidence_text(recent_messages, state.user_text)
        started = _now()

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

        # Terminal-recipient short-circuit: a recipient the provider permanently
        # rejects ("user_id is invalid" on the Bot channel, "-201 user_id is not
        # valid" on OA) can never receive the answer, so generating one costs a full
        # ~9 s turn for nothing — measured at 21 of 284 turns in 24 h (7%, against a
        # 1% error SLO). The dispatcher records the mark on the first such failure;
        # here the turn stands down before Jev, the pending write and the model call.
        # Fail-open: any Redis problem reports "reachable" and the turn proceeds.
        if recipient_id and deps.recipient_unreachable is not None:
            if await deps.recipient_unreachable(
                _channel_for_conversation(conv), recipient_id
            ):
                timings["lane"] = "recipient_unreachable"
                logger.info(
                    "turn skipped: recipient permanently unreachable conversation=%s",
                    state.conversation_id,
                )
                # Single stand-down exit: records the audit row, releases the
                # per-chat lock and stops the typing heartbeat.
                return await _authority_gate(
                    state=state,
                    deps=deps,
                    conv=conv,
                    svc=svc,
                    reason="suppressed",
                    lock_owner=lock_owner,
                    started=started,
                    timings=timings,
                    status_task=status_task,
                )

        # The account label Jev judges the name against: the channel payload name
        # (Zalo bot / OA sender), else the stored provider profile label (Messenger,
        # filled in out of band by profile enrichment).
        profile_name = state.user_name.strip() or _contact_display_name(conv)
        # Messenger leads are contact-keyed (NULL zalo_id), so the recipient id alone
        # would miss them; the contact id is the fallback key.
        contact_id = str(conv.contact_id) if getattr(conv, "contact_id", None) else None

        # Jev fan-out: one decision call per turn. Absent port (tests / disabled) or
        # any failure inside the client degrades to the neutral general/agent route —
        # the bot keeps working without Jev. The call is HTTP-only on its own httpx
        # client and touches no DB, so it is fired before the preamble's remaining
        # DB work (lead lookup, pending write) and awaited after it: its latency
        # overlaps that work instead of serialising behind it, while the shared
        # AsyncSession keeps a single in-flight coroutine at any moment.

        turn_decisions = deps.turn_decisions
        if turn_decisions is not None:

            async def _timed_decide_turn() -> TurnDecisions:
                decisions_t0 = time.monotonic()
                try:
                    return await turn_decisions.decide_turn(
                        user_text=state.user_text,
                        recent_messages=recent_messages,
                        profile_name=profile_name,
                    )
                finally:
                    timings["jev_ms"] = int(round((time.monotonic() - decisions_t0) * 1000))

            jev_task = asyncio.create_task(
                _timed_decide_turn()
            )
        else:
            jev_task = None

        # Resolve the candidate's lead row once and hand it to every adapter call
        # below (stored gender, inference write, prompt context); the adapters keep
        # their own by-zalo/by-contact lookup as the fallback for ports without
        # this seam (tests inject those).
        lead_row: LeadLookup = UNRESOLVED_LEAD
        lead_prefetch: dict[str, LeadLookup] = {}
        lead_resolver = None
        if deps.lead_gender is not None and (recipient_id or contact_id):
            lead_resolver = getattr(deps.lead_gender, "resolve_lead", None)
            if lead_resolver is not None:
                gender_t0 = time.monotonic()
                try:
                    lead_row = await lead_resolver(recipient_id or "", contact_id)
                    lead_prefetch = {"lead": lead_row}
                except Exception:  # noqa: BLE001 — an addressing hint must never break a turn
                    logger.warning("lead resolution failed for %s", recipient_id, exc_info=True)
                _stamp_db(timings, "lead_gender", gender_t0)

        # Read the stored value so the write stays blank-only, and so a stated
        # self-reference in this message can be told apart from an earlier inference.
        stored_gender = ""
        if deps.lead_gender is not None and (recipient_id or contact_id):
            gender_t0 = time.monotonic()
            try:
                stored_gender = await deps.lead_gender.stored_gender(
                    recipient_id or "", contact_id, **lead_prefetch
                )
            except Exception:  # noqa: BLE001 — an addressing hint must never break a turn
                logger.warning("lead gender lookup failed for %s", recipient_id, exc_info=True)
            _stamp_db(timings, "lead_gender", gender_t0)

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

        decisions = await jev_task if jev_task is not None else TurnDecisions(degraded=True)
        if jev_task is None:
            timings["jev_ms"] = 0
        if decisions.degraded:
            timings["jev_degraded"] = True
        else:
            timings["jev_model"] = decisions.model
        # A confident judgment fills a blank; a candidate who explicitly self-refers
        # in this message overrides an earlier inference — the candidate's own word
        # outranks it. Provider/CRM values are preserved unless the candidate states.
        if (
            deps.lead_gender is not None
            and (recipient_id or contact_id)
            and not decisions.degraded
            and decisions.gender in _INFERRED_GENDERS
            and decisions.gender_confidence >= GENDER_INFERENCE_MIN_CONFIDENCE
        ):
            try:
                if await deps.lead_gender.record_inferred_gender(
                    recipient_id or "",
                    decisions.gender,
                    contact_id=contact_id,
                    override=decisions.gender_stated,
                    **lead_prefetch,
                ):
                    # The value itself is candidate data and is deliberately not logged.
                    logger.info("candidate gender inferred conversation=%s", state.conversation_id)
                    stored_gender = decisions.gender
            except Exception:  # noqa: BLE001 — addressing is best-effort
                logger.warning(
                    "candidate gender write failed conversation=%s",
                    state.conversation_id,
                    exc_info=True,
                )
        # Jev judged the provider display label a plausible real human name: fill a
        # blank lead name so the profile panel shows it and the bot stops re-asking.
        # Blank-only by contract (the upsert merge keeps any existing name), so a
        # later candidate-stated name still wins.
        if (
            deps.lead_gender is not None
            and (recipient_id or contact_id)
            and not decisions.degraded
            and decisions.profile_name_is_name
            and profile_name.strip()
        ):
            try:
                name_recorder = getattr(deps.lead_gender, "record_profile_name", None)
                if name_recorder is not None:
                    if await name_recorder(
                        recipient_id or "",
                        profile_name.strip(),
                        contact_id=contact_id,
                        **lead_prefetch,
                    ):
                        logger.info(
                            "candidate profile name captured conversation=%s",
                            state.conversation_id,
                        )
                        # The write may insert a lead after a prefetched miss, or
                        # fill a blank name on an existing row. Observe the committed
                        # result (including a concurrent name the merge preserved)
                        # before building the candidate's prompt.
                        lead_row = UNRESOLVED_LEAD
                        if lead_resolver is not None:
                            refresh_t0 = time.monotonic()
                            try:
                                lead_row = await lead_resolver(recipient_id or "", contact_id)
                            except Exception as exc:  # noqa: BLE001 — context may retry the read
                                logger.warning(
                                    "lead refresh after profile capture failed error_type=%s",
                                    type(exc).__name__,
                                )
                            _stamp_db(timings, "lead_gender", refresh_t0)
            except Exception:  # noqa: BLE001 — name capture is best-effort
                logger.warning(
                    "candidate profile name write failed conversation=%s",
                    state.conversation_id,
                    exc_info=True,
                )
        turn_route = route_from_decisions(state.user_text, decisions)

        provider = provider_from_conversation(conv)

        project_context = None
        if deps.direct_context is not None and turn_route.reason != "vacancy_listing":
            if hasattr(deps.direct_context, "resolve"):
                project_context = await deps.direct_context.resolve(conv, state.user_text)
            elif hasattr(deps.direct_context, "active_context"):
                from app.graph.direct_context import ProjectTurnContext

                # Legacy readers (pre-resolve adapters, test fakes) surface the
                # context directly and duck-type rather than live on the port —
                # the production adapter carries only ``resolve`` — so the read
                # stays deliberately untyped via getattr.
                legacy_direct = await getattr(deps.direct_context, "active_context")()
                if legacy_direct is not None:
                    project_context = ProjectTurnContext(
                        state="FOCUSED",
                        knowledge_mode="DIRECT_CONTEXT",
                        direct_context=legacy_direct,
                    )
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
        # The employee-support OA is not a recruitment channel: no candidate
        # extraction, no lead state, no memory writes for its threads. The flag
        # is computed from the conversation, so it is available here.
        tingting_reset_allowed = await _tingting_reset_allowed(deps, conv)
        allow_recruitment_fast_lane = (
            recruitment_enabled
            and (
                recruitment_capabilities is None
                or "candidate_intake" in recruitment_capabilities
            )
            and not tingting_reset_allowed
        )
        # --- lane: clarification → direct context → agent (see _resolve_lane) ---
        # Progressive send is opt-in (admin ``llm_progressive_send``) and
        # agent-lane only. When it is on, the lane runs as a task while a
        # concurrent sender waits for the first complete, useful bubble; a lane
        # that finishes first — or any non-agent lane — keeps the pre-existing
        # single-message path exactly as it was.
        stream = _ProgressiveStream() if _progressive_send_enabled(deps, svc) else None
        lane_kwargs = {
            "state": state,
            "deps": deps,
            "conv": conv,
            "svc": svc,
            "decisions": decisions,
            "turn_route": turn_route,
            "project_context": project_context,
            "recent_messages": recent_messages,
            "manifest_policy": manifest_policy,
            "provider": provider,
            "recipient_id": recipient_id,
            "timings": timings,
            "started": started,
            "lock_owner": lock_owner,
            "status_task": status_task,
            "t0": t0,
            "lead_row": lead_row,
            "tingting_reset_allowed": tingting_reset_allowed,
            # The composition point owns which agent lane runs; the lane module
            # takes it as an argument instead of importing it back.
            "agent_turn": _agent_turn,
        }
        early: _EarlyBubble | None = None
        if stream is not None:
            lane_task = asyncio.create_task(_resolve_lane(**lane_kwargs, stream=stream))
            try:
                early = await _await_first_bubble(
                    state=state,
                    deps=deps,
                    conv=conv,
                    svc=svc,
                    zalo=zalo,
                    stream=stream,
                    lane_task=lane_task,
                    timings=timings,
                    lock_owner=lock_owner,
                    recipient_id=recipient_id,
                    allowed_text=contact_evidence,
                    status_task=status_task,
                    t0=t0,
                )
            except Exception:  # noqa: BLE001 — the lane still owns the turn
                # A failure in the early sender must never break the turn: the
                # agent is still generating, and the normal path below delivers
                # (or suppresses) the whole reply exactly as before.
                logger.exception(
                    "progressive early send failed; falling back to the normal path "
                    "conversation=%s trace=%s",
                    state.conversation_id,
                    state.trace_id or "-",
                )
                early = None
            lane = await lane_task
        else:
            lane = await _resolve_lane(**lane_kwargs)
        if lane.terminal is not None:
            return lane.terminal
        candidate = lane.candidate
        outcome_label = lane.outcome_label
        faq_metadata = lane.faq_metadata

        # An early bubble only exists when the progressive stream ran (the
        # branch above guards on the stream), so the guard carries both: real
        # narrowing for the stream, not a cast, and no behavior change.
        if stream is not None and early is not None:
            # The first bubble is already with the candidate. Split the raw
            # stream at the sent offset: the remainder is a true suffix, so no
            # text is ever sent twice.
            candidate, early_outcome = await _complete_progressive_prefix(
                early=early,
                stream=stream,
                full_text=lane.candidate,
                state=state,
                deps=deps,
                conv=conv,
                svc=svc,
                timings=timings,
                lock_owner=lock_owner,
                recipient_id=recipient_id,
                allowed_text=contact_evidence,
                started=started,
                outcome_label=outcome_label,
                faq_metadata=faq_metadata,
                manifest_policy=manifest_policy,
                allow_recruitment_fast_lane=allow_recruitment_fast_lane,
                pending_kwargs=pending_kwargs,
                t0=t0,
            )
            if early_outcome is not None:
                return early_outcome

        # --- finalize: all routing lanes converge on one content boundary
        # before persistence and transport. Generated replies receive the full
        # safety policy; curated replies preserve authored formatting while
        # still enforcing the invariant that provider reasoning tags never
        # reach an end user. ---
        candidate = _finalize_user_visible_reply(
            candidate,
            deps=deps,
            generated=lane.generated,
            user_text=state.user_text,
            timings=timings,
        )

        # Deterministic replies (tool safe_reply, curated templates) carry the
        # neutral address form; upgrade it to the resolved form so a known gender
        # is honored there too, not only in LLM prose. Match the sentence-start
        # capitalization too ("Anh/chị" as well as "anh/chị").
        from app.shared.domain.addressing import NEUTRAL_ADDRESS_FORM, address_form

        resolved_address = address_form(stored_gender)
        if resolved_address != NEUTRAL_ADDRESS_FORM:
            candidate = candidate.replace(
                NEUTRAL_ADDRESS_FORM.capitalize(), resolved_address.capitalize()
            ).replace(NEUTRAL_ADDRESS_FORM, resolved_address)

        # Null guard, not an answer check: an empty string cannot be sent as a
        # message. If the agent (or think-block stripping) left nothing to say,
        # the turn is recorded SUPPRESSED with no customer message (the
        # structured log carries the failure).
        if not (candidate or "").strip():
            logger.error(
                "empty reply candidate, turn suppressed conversation=%s trace=%s",
                state.conversation_id,
                state.trace_id or "-",
            )
            return await _authority_gate(
                state=state,
                deps=deps,
                conv=conv,
                svc=svc,
                reason="suppressed",
                lock_owner=lock_owner,
                started=started,
                timings=timings,
                status_task=status_task,
                refresh_conv=True,
            )

        # --- dispatch: claim → send → record (see _claim_and_dispatch). ---
        outcome = await _claim_and_dispatch(
            state=state,
            deps=deps,
            conv=conv,
            svc=svc,
            zalo=zalo,
            candidate=candidate,
            timings=timings,
            started=started,
            lock_owner=lock_owner,
            status_task=status_task,
            recipient_id=recipient_id,
            outcome_label=outcome_label,
            faq_metadata=faq_metadata,
            manifest_policy=manifest_policy,
            allow_recruitment_fast_lane=allow_recruitment_fast_lane,
            t0=t0,
        )
        if outcome is not None:
            return outcome

        # Claim lost: a takeover or newer inbound bumped the version between the
        # recheck and the claim — the drafted candidate is recorded unsent.
        timings["total_ms"] = int(round((time.monotonic() - t0) * 1000))
        _stamp_end_to_end(state, timings)
        return await _authority_gate(
            state=state,
            deps=deps,
            conv=conv,
            svc=svc,
            reason="suppressed",
            reply=candidate,
            outcome_metadata=faq_metadata,
            lock_owner=lock_owner,
            started=started,
            timings=timings,
            status_task=status_task,
        )
    finally:
        await _cancel_status_task(status_task)
        children = [task for task in (jev_task, lane_task) if task is not None]
        for task in children:
            if not task.done():
                task.cancel()
        if children:
            await asyncio.gather(*children, return_exceptions=True)
