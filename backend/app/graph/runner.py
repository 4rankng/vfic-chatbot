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

from app.core.config import get_settings
from app.graph import fast_lane
from app.graph.llm_semaphore import LLMThrottled
from app.graph.prompt_context import build_agent_user_text
from app.graph.prompts import ERROR_REPLY, SLOW_ACK_REPLY
from app.graph.safety import (
    blocklist_hit,
    build_retry_prompt,
    fast_safety_filter,
    parse_verdict,
    retry_exhausted_fallback,
)
from app.graph.types import BotRunState, GraphDeps, TurnOutcome, _now
from app.models.conversation import Message

logger = logging.getLogger(__name__)
RECENT_HISTORY_LIMIT = 16


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


async def _agent_turn(
    state: BotRunState,
    deps: GraphDeps,
    user_text: str,
    *,
    chat_id: str,
    recent_messages: list[Message],
) -> str:
    # System prompt = active persona + master index of active products (best-effort;
    # collapses to AGENT_SYSTEM_PROMPT on any failure so a turn never breaks).
    from app.graph.context import build_system_prompt

    system = await build_system_prompt(deps.retrieval)

    # Fetch existing lead profile so the agent can see what info is already known
    # and subtly ask for the most important missing fields. Best-effort: DB error
    # simply skips injection (a turn never breaks because of this).
    lead_profile = ""
    lead_collection_question = ""
    lead_collection_instruction = ""
    try:
        lead_profile, lead_collection_question = await deps.lead.context(
            chat_id, user_text, recent_messages
        )
        if lead_collection_question:
            lead_collection_instruction = deps.lead.instruction(lead_collection_question)
    except Exception:  # noqa: BLE001
        logger.warning("lead profile fetch failed for %s, skipping injection", chat_id, exc_info=True)

    contextual_user_text = build_agent_user_text(
        chat_id=chat_id,
        current_user_text=user_text,
        recent_messages=recent_messages,
        lead_profile=lead_profile,
        lead_collection_instruction=lead_collection_instruction,
    )
    reply = await deps.agent.agent(
        contextual_user_text, system=system, retrieval=deps.retrieval, embedder=deps.embedder
    )
    return deps.lead.ensure(reply, lead_collection_question)


async def _status_heartbeat(zalo, chat_id: str, *, ack_text: str, settings) -> None:
    """Keep the channel visibly active while a turn is processing.

    Two layers (the OA channel has no functional typing indicator, so the ack
    message is the reliable "bot is active" signal there):

    1. Native typing (best-effort). Pulse ``send_chat_action("typing")`` immediately,
       then every ``typing_heartbeat_seconds``. Real on the Bot channel; a logged
       no-op on OA (``ZaloOASender.send_chat_action``).
    2. Slow-case ack (the reliable OA signal). One-shot at ``slow_ack_seconds``: send
       ``ack_text`` via ``send_message`` — works on both channels. The caller cancels
       this task before dispatching the real answer, so the ack can never land after
       it, and ``ack_fired`` guarantees at most one per turn.

    All send failures are swallowed — status is best-effort and must never break a turn.
    """
    start = time.monotonic()
    next_typing = 0.0
    ack_fired = False
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= next_typing:
            try:
                await zalo.send_chat_action(chat_id, "typing")
            except Exception:  # noqa: BLE001
                pass
            next_typing = elapsed + settings.typing_heartbeat_seconds
        if not ack_fired and elapsed >= settings.slow_ack_seconds:
            ack_fired = True
            try:
                await zalo.send_message(chat_id, ack_text)
            except Exception:  # noqa: BLE001
                pass
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
):
    """Send a terminal fallback (timeout / error) then record the outcome.

    Shared by the agent-deadline and agent-error paths: refresh to read committed
    version/mode, re-check ownership (a concurrent takeover must not be clobbered),
    send only if still owned, and record so the per-chat mutex clears. Returns the
    TurnOutcome dict (``base_outcome`` unless the send itself failed → ``send_failed``).

    The status heartbeat is cancelled first so the one-shot slow-ack can never land
    after this terminal reply.
    """
    if status_task is not None:
        await _cancel_status_task(status_task)
    await deps.db.refresh(conv)
    owned = await svc.recheck_ownership(conv, state.version_at_start)
    send_result = None
    if owned:
        send_result = await zalo.send_message(conv.zalo_chat_id, text)
    await svc.record_bot_outcome(
        conv,
        version_at_start=state.version_at_start,
        reply=text,
        started_at=started,
        sent=bool(send_result and send_result.ok),
        pending_message_id=state.pending_message_id,
        external_error=send_result.error if send_result and not send_result.ok else None,
        zalo_message_id=send_result.msg_id if send_result else None,
    )
    outcome = base_outcome if (send_result is None or send_result.ok) else "send_failed"
    return {"outcome": outcome, "reply": text}


async def run_turn(state: BotRunState, deps: GraphDeps) -> TurnOutcome:
    """Execute one bot turn end-to-end and persist the SENT/SUPPRESSED outcome."""
    svc = deps.conversation
    conv = await svc.get(uuid.UUID(state.conversation_id))
    if conv is None:
        return {"outcome": "error", "reason": "conversation_not_found"}
    zalo = _zalo_for_conversation(deps, conv)
    recent_messages = await svc.last_messages(conv, limit=RECENT_HISTORY_LIMIT)

    # Active-status heartbeat: native typing pulses + a one-shot slow-case ack at
    # slow_ack_seconds (the reliable "bot is active" signal on OA). Cancelled before
    # every real send so the ack never lands after the answer.
    settings = get_settings()
    status_task = asyncio.create_task(
        _status_heartbeat(
            zalo, conv.zalo_chat_id, ack_text=SLOW_ACK_REPLY, settings=settings
        )
    )
    started = _now()
    pending_msg = await svc.record_bot_pending(conv)
    state.pending_message_id = pending_msg.id

    try:
        candidate = ""
        outcome_label = "sent"

        # --- FAQ / template fast lane (zero LLM calls) ---
        # Greetings / thanks / goodbye / help return instant tôi/bạn templates, well
        # inside slow_ack_seconds (so no ack ever fires for them). Factual questions
        # are never templated — they fall through here, then through the FAQ-bypass
        # cascade below, before reaching the RAG + agent path.
        fast = (
            fast_lane.match(state.user_text)
            if settings.faq_fast_lane_enabled
            else None
        )

        # --- deterministic FAQ-bypass cascade (zero LLM calls) ---
        # Runs only for non-template traffic. On a high-confidence hit it answers
        # directly from the knowledge base (0¢, sub-50ms on an embedding-cache hit);
        # on any miss / ambiguity / timeout it abstains (None) and the turn falls
        # through to the agent unchanged. Time-boxed so a cold embed can never burn
        # the turn deadline. None in graph unit tests (no bypass wired).
        bypass = None
        if fast is None and deps.faq_bypass is not None:
            try:
                # Bound the bypass by both the soft cap and the propagated turn
                # deadline (minus the send margin) so a cold-embed bypass can
                # never consume the sliver the agent needs on a tight turn.
                bypass_budget = min(
                    settings.soft_fallback_remaining,
                    max(0.0, _remaining(state) - settings.send_margin_seconds),
                )
                bypass = await asyncio.wait_for(
                    deps.faq_bypass.try_answer(state.user_text),
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
                bypass = None

        if fast is not None:
            candidate = fast.reply
            outcome_label = "faq_cache"
        elif bypass is not None:
            # Admin-authored canonical FAQ text — sent verbatim, like the template
            # lane above (fast_safety_filter is tuned for LLM output, not curated text).
            candidate = bypass.answer
            outcome_label = "faq_bypass"
            logger.info(
                "faq_bypass hit tier=%s score=%.3f reason=%s faq_id=%s",
                bypass.tier, bypass.score, bypass.reason, bypass.faq_id,
            )
        else:
            # --- agent (runs to completion; NO hard cap) ---
            # The propagated deadline is advisory only — it bounds the FAQ-bypass
            # lookup above, never the agent. Cancelling a live LLM call mid-generation
            # produced excessive TIMEOUT fallbacks in prod, so the agent is allowed to
            # finish and its real answer is sent. A genuinely hung provider call is
            # reaped by the RQ job_timeout backstop (>> any realistic turn) and the
            # turn is recovered by the reconcile sweep.
            try:
                raw = await _agent_turn(
                    state,
                    deps,
                    state.user_text,
                    chat_id=conv.zalo_chat_id,
                    recent_messages=recent_messages,
                )
            except LLMThrottled:
                raise  # let worker handle degradation msg (no LLM call)
            except Exception as exc:  # noqa: BLE001 — agent blew up -> graceful fallback
                logger.warning("agent error: %s", exc)
                return await _finish_terminal_reply(
                    state, deps, conv, svc, zalo, ERROR_REPLY, started, "error",
                    status_task=status_task,
                )

            state.reply = raw

            # --- fast safety filter ---
            fs = fast_safety_filter(raw)
            candidate = fs["output"]

            # --- blocklist: hard redirect, no LLM safety judge ---
            # A coarse deny-list hit on the raw output is resolved deterministically
            # (redirect to a fallback) and skips the slower LLM judge entirely.
            if blocklist_hit(raw):
                candidate = retry_exhausted_fallback(state.user_text)
            # --- llm safety check (only when fast filter flagged AND not blocklisted) ---
            elif fs["needs_llm_safety"]:
                verdict = parse_verdict(await deps.safety.safety(candidate))
                if verdict["safe_to_send"]:
                    candidate = verdict["final_answer"] or candidate
                elif state.attempt < 1:
                    state.attempt += 1
                    retry_prompt = build_retry_prompt(state.user_text, candidate, verdict["issue_type"])
                    raw2 = await _agent_turn(
                        state,
                        deps,
                        retry_prompt,
                        chat_id=conv.zalo_chat_id,
                        recent_messages=recent_messages,
                    )
                    state.reply = raw2
                    candidate = fast_safety_filter(raw2)["output"]
                else:
                    candidate = retry_exhausted_fallback(state.user_text)

        # --- pre_send_guard: re-check ownership (catches takeover during generation) ---
        # svc.get() would return the identity-map instance (expire_on_commit=False) and
        # hide a concurrent takeover; refresh() forces a fresh SELECT so the version/mode
        # check below reads committed DB state, not the in-memory snapshot from turn start.
        await deps.db.refresh(conv)
        owned = await svc.recheck_ownership(conv, state.version_at_start)
        if owned:
            await _cancel_status_task(status_task)
            send_result = await zalo.send_message(conv.zalo_chat_id, candidate)
            await svc.record_bot_outcome(
                conv, version_at_start=state.version_at_start, reply=candidate,
                started_at=started, sent=send_result.ok,
                pending_message_id=state.pending_message_id,
                external_error=None if send_result.ok else send_result.error,
                zalo_message_id=send_result.msg_id,
            )
            if not send_result.ok:
                return {
                    "outcome": "send_failed",
                    "reason": send_result.error,
                    "reply": candidate,
                }
            # Lead/memory extraction runs only after a real agent reply was sent (mirrors
            # the legacy "Should Persist?" gate, which never extracted on greetings). A
            # fast-lane template (faq_cache) or a deterministic FAQ-bypass answer
            # (faq_bypass — canonical, already in the KB) carries no Q&A to extract.
            if deps.persist is not None and outcome_label not in ("faq_cache", "faq_bypass"):
                deps.persist(
                    {
                        "chat_id": conv.zalo_chat_id,
                        "user_text": state.user_text,
                        "bot_output": candidate,
                    }
                )
            return {"outcome": outcome_label, "reply": candidate}

        await svc.record_bot_outcome(
            conv, version_at_start=state.version_at_start, reply=candidate,
            started_at=started, sent=False,
            pending_message_id=state.pending_message_id,
        )
        return {"outcome": "suppressed", "reply": candidate}
    finally:
        await _cancel_status_task(status_task)
