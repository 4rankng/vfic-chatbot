"""Proactive follow-up turn — LLM-decided nudge through the safety gate.

Mirrors the reactive pipeline in ``runner.py`` (safety gate, lock/ownership
guards, send, persist) but without an inbound user message and without a BotRun.
The LLM decides whether to send via a **single-call JSON decision** (no tool loop in v1);
the response is parsed, safety-filtered, and persisted with ``bot_run_id IS NULL``
to mark it as a proactive send.

Outcome dict keys: ``outcome`` (sent / suppressed / error), ``reason``, ``reply``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from app.graph.safety import (
    fast_safety_filter,
    retry_exhausted_fallback,
)
from app.graph.types import GraphDeps, _now, _speaker
from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.services.conversation import ConversationService
from app.services.zalo_bot_service import SendResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OUTCOME = "proactive"


def _outcome(kind: str, *, reason: str, reply: str = "") -> dict:
    return {"outcome": f"{_OUTCOME}:{kind}", "reason": reason, "reply": reply}


def parse_proactive_decision(raw: str | dict) -> dict:
    """Parse the LLM's JSON decision for a proactive follow-up.

    Returns ``{"send": bool, "message": str, "reason": str}``. Lenient on
    markdown fences, extra text, or malformed JSON — always returns a safe dict.
    """
    if isinstance(raw, dict):
        raw = json.dumps(raw)
    raw = str(raw).strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```$", "", raw, flags=re.IGNORECASE).strip()

    parsed = None
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            parsed = None

    if not isinstance(parsed, dict):
        return {"send": False, "message": "", "reason": "invalid_decision_json"}

    return {
        "send": bool(parsed.get("send", False)),
        "message": str(parsed.get("message", "")).strip(),
        "reason": str(parsed.get("reason", "")).strip(),
    }


async def _has_worker_reply_since(db, conv_id, since: datetime) -> bool:
    """True if a WORKER message exists in the conversation after ``since``."""
    from sqlalchemy import select, func

    stmt = (
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conv_id,
            Message.sender == MessageSender.WORKER,
            Message.created_at > since,
        )
    )
    result = await db.execute(stmt)
    return result.scalar() > 0


def _build_proactive_user_text(
    *,
    chat_id: str,
    recent_messages: list[Message],
    lead_profile: str = "",
) -> str:
    """Build the contextual user text for the proactive LLM decision."""
    history_lines = [
        f"- {_speaker(m)}: {m.body.strip()}"
        for m in recent_messages
        if (m.body or "").strip() and m.delivery_status != DeliveryStatus.SUPPRESSED
    ]
    if not history_lines:
        history_lines = ["- (chưa có tin nhắn trước đó)"]

    instruction = (
        "\n"
        "BẠn đang CHỦ ĐỘNG nhắn tin cho ứng viên — không có tin nhắn mới từ họ. "
        "Dựa trên hồ sơ ứng viên và lịch sử hội thoại, quyết định xem có nên chủ động liên lạc không.\n\n"
        "Quy tắc quan trọng:\n"
        "- MỘT TIN NHẮN chỉ ĐẶT MỘT CÂU HỎI MỞT — giữ tự nhiên, không ép buộc.\n"
        "- Nếu các tín hiệu gần đây cho thấy họ KHÔNG quan tâm hoặc đang bận → KHÔNG GỬI.\n"
        "- Nếu họ đã thể hiện sự quan tâm trước đó → khơi gợi nhẹ nhàng, một lợi ích cụ thể.\n"
        "- Giọng điệu thân thiện, ngắn gọn (~300 char), không phô trương.\n\n"
        "Bạn PHẢI trả về kết quả dạng JSON:\n"
        '{"send": true hoặc false, "message": "nội dung tin nhắn", "reason": "lý do"}\n'
        "- send=false: bot sẽ KHÔNG GỬI (không cần soạn message).\n"
        "- send=true: message là tin nhắn sẽ gửi trực tiếp.\n"
        "- reason: giải thích ngắn gọn quyết định.\n"
    )

    parts = [f"CHAT_ID: {chat_id}"]
    if lead_profile:
        parts += ["", lead_profile]
    parts += [
        "",
        "LỊCH SỬ GẦN ĐÂY (cũ -> mới):",
        *history_lines,
        "",
        instruction,
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main turn
# ---------------------------------------------------------------------------


async def run_proactive_turn(conv, deps: GraphDeps) -> dict:
    """Execute one proactive follow-up nudge. Returns an outcome dict.

    Steps (per plan §E):
      1. Re-check guards (mode/status/opted_out/cap/lock/inbound).
      2. 48h compliance (Python single-clock, ``last_inbound_at`` writer's clock).
      3. Silence check (auto-opt-out after N ignored nudges).
      4. Acquire lock + capture ``version_at_start``.
      5. Build context (reuse ``build_system_prompt`` + proactive user text).
      6. Single LLM call → JSON decision.
      7. Decision: ``send=False`` → suppress (no increment).
      8. Safety gate (reuse ``fast_safety_filter`` + MiniMax safety LLM).
      9. Last-chance guards (ownership + opted-out + 48h).
     10. Send (``deps.zalo.send``).
     11. Persist (``record_proactive_outcome`` clears lock on any path).
    """
    from app.core.config import (
        PROACTIVE_48H_WINDOW_SECONDS,
        PROACTIVE_FOLLOWUP_CAP,
        PROACTIVE_SILENCE_LIMIT,
    )
    from app.graph.context import build_system_prompt
    from app.services.proactive.repository import conversation_allowed_by_followup_rules
    from app.services.lead.repository import LeadRepository
    from app.services.lead import lead_profile_text

    svc = ConversationService(deps.db)
    now = _now()
    margin = timedelta(seconds=PROACTIVE_48H_WINDOW_SECONDS)
    cap = PROACTIVE_FOLLOWUP_CAP
    silence_limit = PROACTIVE_SILENCE_LIMIT

    # 1. Re-check guards
    await deps.db.refresh(conv)
    mode_value = getattr(conv.mode, "value", conv.mode)
    status_value = getattr(conv.status, "value", conv.status)
    if mode_value not in {"BOT", "SEMI_AUTO"} or status_value != "OPEN":
        return _outcome("suppressed", reason="mode/status")
    if conv.followup_opted_out:
        return _outcome("suppressed", reason="opted_out")
    if conv.followup_count >= cap:
        return _outcome("suppressed", reason="cap_reached")
    if conv.bot_locked_until and conv.bot_locked_until > now:
        return _outcome("suppressed", reason="locked")
    if not conv.last_inbound_at:
        return _outcome("suppressed", reason="no_inbound")

    rule_allowed, rule_reason = await conversation_allowed_by_followup_rules(deps.db, conv)
    if not rule_allowed:
        return _outcome("suppressed", reason=rule_reason)

    # 2. 48h compliance (Python single-clock — same clock that wrote
    #    ``last_inbound_at`` via ``utcnow()`` in ``state.py``)
    elapsed = now - conv.last_inbound_at
    if elapsed > margin:
        logger.info(
            "proactive 48h suppressed: conversation=%s elapsed=%s",
            conv.zalo_chat_id,
            elapsed,
        )
        return _outcome("suppressed", reason="48h_window")

    # 3. Silence check
    if conv.followup_count >= silence_limit and conv.last_followup_at:
        silent = await _has_worker_reply_since(deps.db, conv.id, conv.last_followup_at)
        if not silent:
            conv.followup_opted_out = True
            await deps.db.commit()
            logger.info(
                "proactive silence opt-out: conversation=%s after %d nudges",
                conv.zalo_chat_id,
                conv.followup_count,
            )
            return _outcome("suppressed", reason="silence_optout")

    # 4. Acquire lock
    acquired = await svc.acquire_lock(conv.id)
    if not acquired:
        return _outcome("suppressed", reason="locked")
    version_at_start = conv.version

    try:
        # 5. Build context
        system = await build_system_prompt(deps.db)

        # Fetch lead profile (best-effort — failure just skips injection)
        lead_profile = ""
        recent_messages = await svc.last_messages(conv, limit=16)
        try:
            lead = await LeadRepository(deps.db).by_zalo_id(conv.zalo_chat_id)
            lead_profile = lead_profile_text(lead)
        except Exception:  # noqa: BLE001
            logger.warning("lead fetch failed for %s, skipping", conv.zalo_chat_id, exc_info=True)

        proactive_text = _build_proactive_user_text(
            chat_id=conv.zalo_chat_id,
            recent_messages=recent_messages,
            lead_profile=lead_profile,
        )

        # Stamp attempt timestamp (even before LLM — covers the time cost)
        conv.last_followup_attempt_at = _now()
        await deps.db.flush()

        # 6. Single LLM call → JSON decision
        raw = await deps.agent.agent(
            proactive_text,
            system=system,
            db=deps.db,
            embedder=deps.embedder,
        )
        decision = parse_proactive_decision(raw)

        # 7. Decision gate
        if not decision["send"]:
            logger.info(
                "proactive decision=suppress: conversation=%s reason=%s",
                conv.zalo_chat_id,
                decision["reason"],
            )
            await svc.state.record_proactive_outcome(
                conv, message="", result=SendResult(ok=False, error="agent_decided_not_to_send")
            )
            return _outcome("suppressed", reason=decision["reason"])

        message = decision["message"]
        if not message:
            logger.info("proactive empty message: conversation=%s", conv.zalo_chat_id)
            await svc.state.record_proactive_outcome(
                conv, message="", result=SendResult(ok=False, error="empty_message")
            )
            return _outcome("suppressed", reason="empty_message")

        # 8. Safety gate (reuse fast filter + LLM safety)
        fs = fast_safety_filter(message)
        candidate = fs["output"]

        if fs["needs_llm_safety"]:
            from app.graph.safety import parse_verdict

            verdict = parse_verdict(await deps.safety.safety(candidate))
            if verdict["safe_to_send"]:
                candidate = verdict["final_answer"] or candidate
            else:
                logger.info("proactive safety blocked: conversation=%s", conv.zalo_chat_id)
                await svc.state.record_proactive_outcome(
                    conv, message=candidate, result=SendResult(ok=False, error="safety_blocked")
                )
                return _outcome("suppressed", reason="safety_blocked")
        else:
            candidate = fs["output"]

        # 9. Last-chance guards (re-read from DB for takeovers/opt-outs)
        await deps.db.refresh(conv)
        if conv.followup_opted_out:
            await svc.state.release_lock(conv)
            await deps.db.commit()
            return _outcome("suppressed", reason="opted_out_during_generation")
        rule_allowed, rule_reason = await conversation_allowed_by_followup_rules(deps.db, conv)
        if not rule_allowed:
            await svc.state.release_lock(conv)
            await deps.db.commit()
            return _outcome("suppressed", reason=f"rule_{rule_reason}")
        owned = await svc.recheck_ownership(conv, version_at_start)
        if not owned:
            await svc.state.release_lock(conv)
            await deps.db.commit()
            return _outcome("suppressed", reason="ownership_lost")
        # Re-check 48h one more time (covers slow LLM/safety generation)
        if _now() - conv.last_inbound_at > margin:
            await svc.state.release_lock(conv)
            await deps.db.commit()
            return _outcome("suppressed", reason="48h_window_post_generation")

        # 10. Send
        sender = deps.zalo.for_conversation(conv) if hasattr(deps.zalo, "for_conversation") else deps.zalo
        result = await sender.send_message(conv.zalo_chat_id, candidate)

    except Exception as exc:
        logger.warning("proactive turn error: conversation=%s error=%s", conv.zalo_chat_id, exc)
        result = SendResult(ok=False, error=str(exc))
        candidate = candidate or retry_exhausted_fallback("")

    # 11. Persist (always — clears lock, records SENT/FAILED message,
    #     handles cadence count)
    await svc.state.record_proactive_outcome(conv, message=candidate, result=result)
    return {"outcome": "sent" if result.ok else "send_failed", "reply": candidate}
