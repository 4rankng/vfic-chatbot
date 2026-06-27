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

LLM/embedder/Zalo/DB are injected via GraphDeps (now defined in ``app.graph.types``), so
the safety/ownership/suppress branches are unit-testable with fakes (no API keys needed).
Live parity (acceptance #4 grounding / #5 off-topic via real MiniMax) is exercised through
graph/factories.py + graph/clients.py. ``BotRunState`` / ``GraphDeps`` are re-exported here
for backward-compatible imports.
"""
from __future__ import annotations

import logging
import uuid

from app.graph.prompts import ERROR_REPLY
from app.graph.safety import (
    build_retry_prompt,
    fast_safety_filter,
    parse_verdict,
    retry_exhausted_fallback,
)
from app.graph.types import BotRunState, GraphDeps, _now
from app.services.conversation import ConversationService

logger = logging.getLogger(__name__)


async def _agent_turn(state: BotRunState, deps: GraphDeps, user_text: str) -> str:
    # System prompt = active persona + master index of active products (best-effort;
    # collapses to AGENT_SYSTEM_PROMPT on any failure so a turn never breaks).
    from app.graph.context import build_system_prompt

    system = await build_system_prompt(deps.db)
    return await deps.agent.agent(
        user_text, system=system, db=deps.db, embedder=deps.embedder
    )


async def run_turn(state: BotRunState, deps: GraphDeps) -> dict:
    """Execute one bot turn end-to-end and persist the SENT/SUPPRESSED outcome."""
    svc = ConversationService(deps.db)
    conv = await svc.get(uuid.UUID(state.conversation_id))
    if conv is None:
        return {"outcome": "error", "reason": "conversation_not_found"}

    # typing (best-effort; never blocks the run)
    try:
        await deps.zalo.typing(conv.zalo_chat_id)
    except Exception:  # noqa: BLE001
        pass

    started = _now()

    # --- agent ---
    try:
        raw = await _agent_turn(state, deps, state.user_text)
    except Exception as exc:  # noqa: BLE001 — agent blew up -> graceful fallback
        logger.warning("agent error: %s", exc)
        owned = await svc.recheck_ownership(conv, state.version_at_start)
        if owned:
            await deps.zalo.send(conv.zalo_chat_id, ERROR_REPLY)
        await svc.record_bot_outcome(
            conv, version_at_start=state.version_at_start, reply=ERROR_REPLY,
            started_at=started, sent=owned,
        )
        return {"outcome": "error", "reply": ERROR_REPLY}

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
            raw2 = await _agent_turn(state, deps, retry_prompt)
            state.reply = raw2
            candidate = fast_safety_filter(raw2)["output"]
        else:
            candidate = retry_exhausted_fallback(state.user_text)

    # --- pre_send_guard: re-check ownership (catches takeover during generation) ---
    # svc.get() would return the identity-map instance (expire_on_commit=False) and
    # hide a concurrent takeover; refresh() forces a fresh SELECT so the version/mode
    # check below reads committed DB state, not the in-memory snapshot from turn start.
    await svc.db.refresh(conv)
    owned = await svc.recheck_ownership(conv, state.version_at_start)
    if owned:
        await deps.zalo.send(conv.zalo_chat_id, candidate)
        await svc.record_bot_outcome(
            conv, version_at_start=state.version_at_start, reply=candidate,
            started_at=started, sent=True,
        )
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
    )
    return {"outcome": "suppressed", "reply": candidate}
