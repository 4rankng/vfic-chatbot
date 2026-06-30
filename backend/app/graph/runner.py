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
import re
import uuid
from contextlib import suppress

from app.graph.llm_semaphore import LLMThrottled
from app.graph.prompts import ERROR_REPLY
from app.graph.safety import (
    build_retry_prompt,
    fast_safety_filter,
    parse_verdict,
    retry_exhausted_fallback,
)
from app.graph.types import BotRunState, GraphDeps, _now, _speaker
from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.services.conversation import ConversationService

logger = logging.getLogger(__name__)
ZALO_TYPING_HEARTBEAT_SECONDS = 4.0
RECENT_HISTORY_LIMIT = 16
_PHONE_RE = re.compile(r"(?:\+?84|0)(?:\D*\d){8,10}\b")


def _last_bot_message(recent_messages: list[Message]) -> str:
    for msg in reversed(recent_messages):
        if msg.sender == MessageSender.BOT and (msg.body or "").strip():
            return msg.body.strip()
    return ""


def _bot_asked_for_name(text: str) -> bool:
    lowered = (text or "").casefold()
    return "tên" in lowered and any(token in lowered for token in ("bạn", "cho tôi", "cho mình", "xin"))


def _current_text_answers_name(current_user_text: str, recent_messages: list[Message]) -> bool:
    text = re.sub(r"\s+", " ", current_user_text or "").strip()
    if not text or _PHONE_RE.search(text):
        return False
    lowered = text.casefold()
    if any(marker in lowered for marker in ("tôi tên", "mình tên", "em tên", "anh tên", "chị tên", "tên là")):
        return True
    if _bot_asked_for_name(_last_bot_message(recent_messages)):
        return 1 <= len(text.split()) <= 5 and len(text) <= 50
    return False


def _lead_has_value(lead: dict | None, key: str) -> bool:
    if not lead:
        return False
    return bool(str(lead.get(key) or "").strip())


def _lead_collection_instruction(
    *,
    question: str,
) -> str:
    return (
        "THU THẬP THÔNG TIN ỨNG VIÊN:\n"
        "- Sau khi trả lời nội dung chính, hãy kết thúc bằng câu hỏi thu thập "
        "(hoặc lồng ghép tự nhiên vào câu trả lời):\n"
        f"  → {question}\n"
        "- Chỉ hỏi 1 trường trong tin nhắn này, ưu tiên giữ mạch hội thoại tự nhiên."
    )


# Askable fields: (db_key, question).  Order = probing priority.
# ``notes`` is passive capture (never probed — no natural "what are your notes?" question).
_ASKABLE_FIELDS: list[tuple[str, str]] = [
    ("name", "Bạn cho tôi xin tên để tiện hỗ trợ nhé?"),
    ("phone", "Bạn cho tôi xin số điện thoại để VFIC liên hệ hỗ trợ ứng tuyển nhé?"),
    ("desired_job", "Bạn muốn ứng tuyển vị trí công việc nào?"),
    ("region", "Bạn muốn làm việc ở tỉnh/thành nào?"),
    ("living_area", "Bạn đang sinh sống ở khu vực nào?"),
    ("expected_salary", "Bạn mong muốn mức lương khoảng bao nhiêu?"),
]

# Cheap keyword checks — if the current turn mentions any of these, assume the
# user already answered the corresponding field this turn (prevents re-asking
# before the async extraction worker updates the lead row).
# Each tuple includes both accented AND unaccented forms so mobile users who
# type without diacritics (common on Zalo) are still detected.
_FIELD_DETECT_KW: dict[str, tuple[str, ...]] = {
    "desired_job": ("làm việc", "công việc", "vị trí", "ứng tuyển", "muốn làm", "tìm việc"),
    "region": (
        "tỉnh", "thành phố",
        "hải phòng", "hai phong",
        "hà nội", "ha noi",
        "đà nẵng", "da nang",
        "hcm", "hồ chí minh", "ho chi minh",
        "bình dương", "binh duong",
        "đồng nai", "dong nai",
        "bắc ninh", "bac ninh",
        "hưng yên", "hung yen",
    ),
    "living_area": ("sống ở", "đang sống", "sinh sống", "quê ở", "địa chỉ"),
    "expected_salary": ("lương", "triệu"),
}


def _lead_collection_question(
    *,
    lead: dict | None,
    current_user_text: str,
    recent_messages: list[Message],
) -> str:
    text = current_user_text or ""
    for field, question in _ASKABLE_FIELDS:
        if _lead_has_value(lead, field):
            continue
        # Per-field same-turn "already answered" guards.
        if field == "name" and _current_text_answers_name(text, recent_messages):
            continue
        if field == "phone" and bool(_PHONE_RE.search(text)):
            continue
        keywords = _FIELD_DETECT_KW.get(field)
        if keywords:
            lowered = text.casefold()
            if any(kw in lowered for kw in keywords):
                continue
        return question
    return ""


def _compact_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def _ensure_lead_collection_question(reply: str, question: str) -> str:
    if not question:
        return reply
    text = (reply or "").strip()
    if not text:
        return question
    if _compact_for_match(question.rstrip("?")) in _compact_for_match(text):
        return text
    # Always append — never replace the model's last paragraph.
    return f"{text}\n\n{question}"


def _build_agent_user_text(
    *,
    chat_id: str,
    current_user_text: str,
    recent_messages: list[Message],
    lead_profile: str = "",
    lead_collection_instruction: str = "",
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
            f"- {_speaker(m)}: {m.body.strip()}" for m in history
        ]
    else:
        history_lines = ["- (chưa có tin nhắn trước đó)"]

    parts: list[str] = [
        f"CHAT_ID để tra cứu memory khi cần: {chat_id}",
    ]
    if lead_profile:
        parts += ["", lead_profile]
    if lead_collection_instruction:
        parts += ["", lead_collection_instruction]
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
    lead_collection_question = ""
    lead_collection_instruction = ""
    try:
        lead = await LeadRepository(deps.db).by_zalo_id(chat_id)
        lead_profile = lead_profile_text(lead)
        lead_collection_question = _lead_collection_question(
            lead=lead,
            current_user_text=user_text,
            recent_messages=recent_messages,
        )
        if lead_collection_question:
            lead_collection_instruction = _lead_collection_instruction(
                question=lead_collection_question
            )
    except Exception:  # noqa: BLE001
        logger.warning("lead profile fetch failed for %s, skipping injection", chat_id, exc_info=True)

    contextual_user_text = _build_agent_user_text(
        chat_id=chat_id,
        current_user_text=user_text,
        recent_messages=recent_messages,
        lead_profile=lead_profile,
        lead_collection_instruction=lead_collection_instruction,
    )
    reply = await deps.agent.agent(
        contextual_user_text, system=system, db=deps.db, embedder=deps.embedder
    )
    return _ensure_lead_collection_question(reply, lead_collection_question)


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
            await svc.db.refresh(conv)
            owned = await svc.recheck_ownership(conv, state.version_at_start)
            if owned:
                await deps.zalo.send(conv.zalo_chat_id, ERROR_REPLY)
            await svc.record_bot_outcome(
                conv, version_at_start=state.version_at_start, reply=ERROR_REPLY,
                started_at=started, sent=owned,
                pending_message_id=state.pending_message_id,
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
                pending_message_id=state.pending_message_id,
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
            pending_message_id=state.pending_message_id,
        )
        return {"outcome": "suppressed", "reply": candidate}
    finally:
        typing_task.cancel()
        with suppress(asyncio.CancelledError):
            await typing_task
