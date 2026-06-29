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

import asyncio
import logging
import uuid
from contextlib import suppress

from app.graph.prompts import ERROR_REPLY
from app.graph.safety import (
    build_retry_prompt,
    fast_safety_filter,
    parse_verdict,
    retry_exhausted_fallback,
)
from app.graph.types import BotRunState, GraphDeps, _now
from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.services.conversation import ConversationService

logger = logging.getLogger(__name__)
ZALO_TYPING_HEARTBEAT_SECONDS = 4.0
RECENT_HISTORY_LIMIT = 16


def _history_speaker(msg: Message) -> str:
    if msg.sender == MessageSender.WORKER:
        return "Ứng viên"
    if msg.sender == MessageSender.BOT:
        return "Bot"
    if msg.sender == MessageSender.RECRUITER:
        return "Nhân viên"
    return "Hệ thống"


def _build_agent_user_text(
    *,
    chat_id: str,
    current_user_text: str,
    recent_messages: list[Message],
    lead_profile: str = "",
) -> str:
    """Give the agent the actual chat state, not just the latest short reply.

    Zalo follow-ups are often terse ("Lê Chân", "ca đêm", "có xe không?").
    Without the nearby transcript the model treats those as new conversations and
    falls back to the greeting flow. The webhook already persists inbound before
    enqueueing the turn, so this wrapper supplies the preceding context while
    keeping the current user message explicit.
    """
    history = [
        m
        for m in recent_messages
        if (m.body or "").strip() and m.delivery_status != DeliveryStatus.SUPPRESSED
    ]
    if (
        history
        and history[-1].sender == MessageSender.WORKER
        and history[-1].body.strip() == current_user_text.strip()
    ):
        history = history[:-1]

    if history:
        history_lines = [
            f"- {_history_speaker(m)}: {m.body.strip()}" for m in history
        ]
    else:
        history_lines = ["- (chưa có tin nhắn trước đó)"]

    parts: list[str] = [
        f"CHAT_ID để tra cứu memory khi cần: {chat_id}",
    ]
    if lead_profile:
        parts += ["", lead_profile]
    parts += [
        "",
        "LỊCH SỬ GẦN ĐÂY (cũ -> mới):",
        *history_lines,
        "",
        "TIN NHẮN HIỆN TẠI CỦA ỨNG VIÊN:",
        current_user_text,
        "",
        "Hãy trả lời tin nhắn hiện tại dựa trên lịch sử trên. "
        "Nếu đây là câu trả lời ngắn cho câu hỏi trước đó, tiếp tục đúng mạch hội thoại; "
        "không chào lại hoặc hỏi lại thông tin đã có.",
    ]
    return "\n".join(parts)


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
    from app.services.lead_repository import LeadRepository
    from app.services.lead_service import lead_profile_text

    system = await build_system_prompt(deps.db)

    # Fetch existing lead profile so the agent can see what info is already known
    # and subtly ask for the most important missing fields. Best-effort: DB error
    # simply skips injection (a turn never breaks because of this).
    lead_profile = ""
    try:
        lead = await LeadRepository(deps.db).by_zalo_id(chat_id)
        lead_profile = lead_profile_text(lead)
    except Exception:  # noqa: BLE001
        logger.warning("lead profile fetch failed for %s, skipping injection", chat_id, exc_info=True)

    contextual_user_text = _build_agent_user_text(
        chat_id=chat_id,
        current_user_text=user_text,
        recent_messages=recent_messages,
        lead_profile=lead_profile,
    )
    return await deps.agent.agent(
        contextual_user_text, system=system, db=deps.db, embedder=deps.embedder
    )


async def _typing_heartbeat(deps: GraphDeps, chat_id: str) -> None:
    """Keep Zalo's transient typing status visible while a turn is processing."""
    while True:
        try:
            await deps.zalo.typing(chat_id)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(ZALO_TYPING_HEARTBEAT_SECONDS)


async def run_turn(state: BotRunState, deps: GraphDeps) -> dict:
    """Execute one bot turn end-to-end and persist the SENT/SUPPRESSED outcome."""
    svc = ConversationService(deps.db)
    conv = await svc.get(uuid.UUID(state.conversation_id))
    if conv is None:
        return {"outcome": "error", "reason": "conversation_not_found"}
    recent_messages = await svc.last_messages(conv, limit=RECENT_HISTORY_LIMIT)

    typing_task = asyncio.create_task(_typing_heartbeat(deps, conv.zalo_chat_id))
    started = _now()

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
    finally:
        typing_task.cancel()
        with suppress(asyncio.CancelledError):
            await typing_task
