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
import uuid
from contextlib import suppress

from app.graph.llm_semaphore import LLMThrottled
from app.graph.prompt_context import build_agent_user_text
from app.graph.prompts import ERROR_REPLY
from app.graph.safety import (
    build_retry_prompt,
    fast_safety_filter,
    parse_verdict,
    retry_exhausted_fallback,
)
from app.graph.types import BotRunState, GraphDeps, TurnOutcome, _now
from app.models.conversation import Message

logger = logging.getLogger(__name__)
ZALO_TYPING_HEARTBEAT_SECONDS = 4.0
RECENT_HISTORY_LIMIT = 16


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


async def _typing_heartbeat(zalo, chat_id: str) -> None:
    """Keep Zalo's transient typing status visible while a turn is processing."""
    while True:
        try:
            await zalo.send_chat_action(chat_id, "typing")
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(ZALO_TYPING_HEARTBEAT_SECONDS)


async def run_turn(state: BotRunState, deps: GraphDeps) -> TurnOutcome:
    """Execute one bot turn end-to-end and persist the SENT/SUPPRESSED outcome."""
    svc = deps.conversation
    conv = await svc.get(uuid.UUID(state.conversation_id))
    if conv is None:
        return {"outcome": "error", "reason": "conversation_not_found"}
    zalo = _zalo_for_conversation(deps, conv)
    recent_messages = await svc.last_messages(conv, limit=RECENT_HISTORY_LIMIT)

    typing_task = asyncio.create_task(_typing_heartbeat(zalo, conv.zalo_chat_id))
    started = _now()
    pending_msg = await svc.record_bot_pending(conv)
    state.pending_message_id = pending_msg.id

    try:
        # --- agent ---
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
            # refresh to read committed version/mode — see recheck_ownership docstring
            await deps.db.refresh(conv)
            owned = await svc.recheck_ownership(conv, state.version_at_start)
            send_result = None
            if owned:
                send_result = await zalo.send_message(conv.zalo_chat_id, ERROR_REPLY)
            await svc.record_bot_outcome(
                conv, version_at_start=state.version_at_start, reply=ERROR_REPLY,
                started_at=started, sent=bool(send_result and send_result.ok),
                pending_message_id=state.pending_message_id,
                external_error=send_result.error if send_result and not send_result.ok else None,
                zalo_message_id=send_result.msg_id if send_result else None,
            )
            return {
                "outcome": "error" if send_result is None or send_result.ok else "send_failed",
                "reply": ERROR_REPLY,
            }

        state.reply = raw

        # --- fast safety filter ---
        fs = fast_safety_filter(raw)
        candidate = fs["output"]

        # --- llm safety check (only when fast filter flagged) ---
        if fs["needs_llm_safety"]:
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
            # Lead/memory extraction runs only after a real reply was sent (mirrors the
            # legacy "Should Persist?" gate, which never extracted on greetings/suppressed).
            if deps.persist is not None:
                deps.persist(
                    {
                        "chat_id": conv.zalo_chat_id,
                        "user_text": state.user_text,
                        "bot_output": candidate,
                    }
                )
            return {"outcome": "sent", "reply": candidate}

        await svc.record_bot_outcome(
            conv, version_at_start=state.version_at_start, reply=candidate,
            started_at=started, sent=False,
            pending_message_id=state.pending_message_id,
        )
        return {"outcome": "suppressed", "reply": candidate}
    finally:
        typing_task.cancel()
        with suppress(asyncio.CancelledError):
            await typing_task
