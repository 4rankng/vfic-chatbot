"""Proactive follow-up turn — LLM-decided nudge.

Mirrors the reactive pipeline in ``runner.py`` (lock/ownership guards, send,
persist) but without an inbound user message and without a BotRun.
The LLM decides whether to send via a **single-call JSON decision** (no tool loop in v1);
the response is parsed and persisted with ``bot_run_id IS NULL``
to mark it as a proactive send.

Outcome dict keys: ``outcome`` (sent / suppressed / error), ``reason``, ``reply``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from inspect import iscoroutinefunction
from typing import Any, Awaitable, Callable, TypedDict, cast

from app.graph.message_values import delivery_is, sender_is
from app.graph.ports import SendOutcome
from app.graph.prompt_context import history_line
from app.graph.think_strip import contains_tool_protocol, strip_provider_artifacts
from app.graph.types import GraphDeps, TurnOutcome, _now
from app.recruitment.application.ports import ProactiveStatePort

logger = logging.getLogger(__name__)


class ProactiveDecision(TypedDict):
    """Parsed LLM JSON decision for a proactive nudge (see parse_proactive_decision)."""

    send: bool
    message: str
    reason: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OUTCOME = "proactive"


def _outcome(kind: str, *, reason: str, reply: str = "") -> TurnOutcome:
    return {"outcome": f"{_OUTCOME}:{kind}", "reason": reason, "reply": reply}


def parse_proactive_decision(raw: str | dict) -> ProactiveDecision:
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


class _GraphTestProactiveState:
    """Compatibility state used only by graph tests that inject a fake DB."""

    def __init__(self, db) -> None:
        self._db = db

    async def refresh(self, conversation) -> None:
        await self._db.refresh(conversation)

    async def flush(self) -> None:
        await self._db.flush()

    async def commit(self) -> None:
        await self._db.commit()

    async def has_worker_reply_since(self, conversation_id, since) -> bool:
        checker = getattr(self._db, "has_worker_reply_since", None)
        if checker is None:
            return True
        return bool(await checker(conversation_id, since))

    async def opt_out_for_silence(self, conversation) -> None:
        conversation.followup_opted_out = True
        await self._db.commit()

    async def stamp_attempt(self, conversation, attempted_at) -> None:
        conversation.last_followup_attempt_at = attempted_at
        await self._db.flush()


def _build_proactive_user_text(
    *,
    chat_id: str,
    recent_messages: list[Any],
    lead_profile: str = "",
) -> str:
    """Build the contextual user text for the proactive LLM decision."""
    history_lines = [
        line
        for m in recent_messages
        if (m.body or "").strip()
        and not delivery_is(m, "SUPPRESSED")
        and (line := history_line(m)) is not None
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


async def run_proactive_turn(conv, deps: GraphDeps) -> TurnOutcome:
    """Execute one proactive follow-up nudge. Returns an outcome dict.

    Steps (per plan §E):
      1. Re-check guards (mode/status/opted_out/cap/lock/inbound).
      2. 48h compliance (Python single-clock, ``last_inbound_at`` writer's clock).
      3. Silence check (auto-opt-out after N ignored nudges).
      4. Acquire lock + capture ``version_at_start``.
      5. Build context (reuse ``build_system_prompt`` + proactive user text).
      6. Single LLM call → JSON decision.
      7. Decision: ``send=False`` → suppress (no increment).
      8. Structural gate: strip provider reasoning; nothing else rewrites it.
      9. Last-chance guards (ownership + opted-out + 48h).
     10. Send (``deps.zalo.send``).
     11. Persist (``record_proactive_outcome`` clears lock on any path).
    """
    from app.recruitment.domain.proactive_policy import (
        PROACTIVE_48H_WINDOW_SECONDS,
        PROACTIVE_FOLLOWUP_CAP,
        PROACTIVE_SILENCE_LIMIT,
    )
    from app.graph.context import build_system_prompt
    from app.graph.lanes import _tingting_account_conversation
    from app.graph.tingting_guide import tingting_support_system_prompt
    from app.recruitment.domain.provider import (
        provider_from_conversation,
        recipient_from_conversation,
    )

    svc = deps.conversation
    # Proactive runs always wire the follow-up guard — the None default on
    # GraphDeps.followup_allowed exists for reactive-only tests — so bind the
    # callable once and keep the two guard sites below branch-free.
    followup_allowed = cast(
        "Callable[[Any], Awaitable[tuple[bool, str]]]", deps.followup_allowed
    )
    injected_proactive_state = getattr(deps, "proactive_state", None)
    proactive_state: ProactiveStatePort = (
        injected_proactive_state
        if injected_proactive_state is not None
        else _GraphTestProactiveState(deps.db)
    )
    now = _now()
    margin = timedelta(seconds=PROACTIVE_48H_WINDOW_SECONDS)
    cap = PROACTIVE_FOLLOWUP_CAP
    silence_limit = PROACTIVE_SILENCE_LIMIT
    provider = provider_from_conversation(conv)
    # Eligibility for a proactive nudge requires an inbound message inside the
    # 48h window, and an inbound message always persists the sender id on the
    # conversation, so the port's ``str | None`` never carries None here.
    # Narrow once at the boundary instead of branching at each typed consumer.
    recipient_id = cast("str", recipient_from_conversation(conv))

    if deps.runtime_policy is not None:
        policy = await deps.runtime_policy.resolve_active_policy()
        if policy is None or policy.pack_key != "recruitment":
            return _outcome("suppressed", reason="proactive_not_enabled")

    # 1. Re-check guards
    await proactive_state.refresh(conv)
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

    rule_allowed, rule_reason = await followup_allowed(conv)
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
        silent = await proactive_state.has_worker_reply_since(
            conv.id,
            conv.last_followup_at,
        )
        if not silent:
            await proactive_state.opt_out_for_silence(conv)
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
    lock_owner = None if acquired is True else acquired
    version_at_start = conv.version
    # Initialized before the try so a failure during context build / LLM call
    # still reaches the finalizer: record_proactive_outcome clears the lock and
    # durably records the failure instead of crashing on UnboundLocalError.
    candidate = ""
    pending_message_id: int | None = None
    outbox_channel: str | None = None
    outbox_payload: dict | None = None

    try:
        # 5. Build context
        if _tingting_account_conversation(conv):
            # The support OA never receives the recruitment preamble (project
            # directory, advertising rules): identity-scoped, so an unconfigured
            # reset link cannot leak it here. Same prompt as the reactive turn.
            configured_reader = getattr(deps.retrieval, "tingting_api_configured", None)
            tingting_configured = False
            if configured_reader is not None:
                try:
                    tingting_configured = bool(await configured_reader())
                except Exception as exc:  # noqa: BLE001 — a prompt gate must never break a nudge
                    logger.warning(
                        "tingting api configured-read failed error_type=%s", type(exc).__name__
                    )
            hotline_reader = getattr(deps.retrieval, "tingting_hotline", None)
            tingting_hotline = ""
            if hotline_reader is not None:
                try:
                    tingting_hotline = str(await hotline_reader() or "").strip()
                except Exception as exc:  # noqa: BLE001 — a prompt read must never break a nudge
                    logger.warning(
                        "tingting hotline read failed error_type=%s", type(exc).__name__
                    )
            system = tingting_support_system_prompt(
                include_guide=tingting_configured, hotline=tingting_hotline
            )
        else:
            system, _ = await build_system_prompt(
                deps.retrieval,
                provider=provider,
            )
        project_context = (
            await deps.direct_context.resolve(conv, "")
            if deps.direct_context is not None and hasattr(deps.direct_context, "resolve")
            else None
        )
        if project_context is not None and project_context.state == "FOCUSED":
            system += (
                "\n\nDự án đang được chọn: "
                f"{project_context.project_name} (slug: {project_context.project_slug}). "
                "Không dùng dữ liệu chi tiết của dự án khác."
            )

        # Fetch lead profile (best-effort — failure just skips injection)
        lead_profile = ""
        recent_messages = await svc.last_messages(conv, limit=16)
        try:
            if deps.lead is not None:
                lead_profile = await deps.lead.profile_text(recipient_id)
        except Exception:  # noqa: BLE001
            logger.warning("lead fetch failed for %s, skipping", conv.zalo_chat_id, exc_info=True)

        proactive_text = _build_proactive_user_text(
            chat_id=recipient_id,
            recent_messages=recent_messages,
            lead_profile=lead_profile,
        )

        # Stamp attempt timestamp (even before LLM — covers the time cost)
        await proactive_state.stamp_attempt(conv, _now())

        # 6. Single LLM call → JSON decision
        proactive_agent_kwargs = {
            "system": system,
            "retrieval": deps.retrieval,
            "embedder": deps.embedder,
        }
        if project_context is not None and project_context.direct_context is not None:
            # The retired direct lane is folded in: the KB full text rides in
            # the prompt and no tool is bound (a tool cannot add evidence the
            # KB already carries). The agent authors the nudge.
            from app.graph.direct_context import build_direct_system

            proactive_agent_kwargs["system"] = (
                f"{system}\n\n"
                "=== KIẾN THỨC DỰ ÁN (toàn văn, nguồn chính thức) ===\n"
                f"{build_direct_system(project_context.direct_context)}"
            )
            proactive_agent_kwargs["resolved_tool_registry"] = frozenset()
        elif (
            project_context is not None
            and project_context.state == "FOCUSED"
            and project_context.knowledge_mode == "RAG"
        ):
            proactive_agent_kwargs["forced_project_slug"] = project_context.project_slug
        raw = await deps.agent.agent(proactive_text, **proactive_agent_kwargs)
        decision = parse_proactive_decision(raw)

        # 7. Decision gate
        if not decision["send"]:
            logger.info(
                "proactive decision=suppress: conversation=%s reason=%s",
                conv.zalo_chat_id,
                decision["reason"],
            )
            await svc.state.record_proactive_outcome(
                conv,
                message="",
                result=SendOutcome(ok=False, error="agent_decided_not_to_send"),
                lock_owner=lock_owner,
            )
            return _outcome("suppressed", reason=decision["reason"])

        message = decision["message"]
        if not message:
            logger.info("proactive empty message: conversation=%s", conv.zalo_chat_id)
            await svc.state.record_proactive_outcome(
                conv,
                message="",
                result=SendOutcome(ok=False, error="empty_message"),
                lock_owner=lock_owner,
            )
            return _outcome("suppressed", reason="empty_message")

        # 8. Structural output gate (no LLM judge, no lexical filtering, no
        #    reply-policy layer: the only transformation is the reasoning strip).
        # The LLM safety judge was removed (p50 10.3s, as expensive as the agent
        # call). Lexical blocklists were removed too: they could not separate an
        # injection echo from ordinary Vietnamese and silently suppressed valid
        # nudges. What is left is shape, not meaning:
        #   - nothing survived the reasoning strip → suppress (nothing to send)
        #   - otherwise send as generated (the truncation that used to live here
        #     was removed with the reply-policy layer; a long nudge is sent in
        #     channel-sized bubbles by the sender instead)
        candidate = strip_provider_artifacts(message)

        if not candidate.strip() or contains_tool_protocol(candidate):
            logger.info("proactive message empty after cleaning: conversation=%s", conv.zalo_chat_id)
            await svc.state.record_proactive_outcome(
                conv,
                message=candidate,
                result=SendOutcome(ok=False, error="safety_blocked"),
                lock_owner=lock_owner,
            )
            return _outcome("suppressed", reason="safety_blocked")

        # 9. Last-chance guards (re-read from DB for takeovers/opt-outs)
        await proactive_state.refresh(conv)
        if conv.followup_opted_out:
            await svc.state.release_lock(conv, lock_owner=lock_owner)
            await proactive_state.commit()
            return _outcome("suppressed", reason="opted_out_during_generation")
        rule_allowed, rule_reason = await followup_allowed(conv)
        if not rule_allowed:
            await svc.state.release_lock(conv, lock_owner=lock_owner)
            await proactive_state.commit()
            return _outcome("suppressed", reason=f"rule_{rule_reason}")
        owned = await svc.recheck_ownership(conv, version_at_start, lock_owner=lock_owner)
        if not owned:
            await svc.state.release_lock(conv, lock_owner=lock_owner)
            await proactive_state.commit()
            return _outcome("suppressed", reason="ownership_lost")
        # Re-check 48h one more time (covers slow LLM generation)
        if _now() - conv.last_inbound_at > margin:
            await svc.state.release_lock(conv, lock_owner=lock_owner)
            await proactive_state.commit()
            return _outcome("suppressed", reason="48h_window_post_generation")

        # 10. Persist the command, then dispatch it.  The production service
        # always takes this durable path; the direct branch retains pure graph
        # unit-test fakes that intentionally have no persistence facade.
        outbox_channel = provider
        quote_message_id = next(
            (
                item.zalo_message_id
                for item in reversed(recent_messages)
                if sender_is(item, "WORKER") and item.zalo_message_id
            ),
            None,
        )
        if outbox_channel == "zalo_oa" and not quote_message_id:
            result = SendOutcome(ok=False, error="zalo_oa_requires_inbound_message_id")
        else:
            outbox_payload = {"chat_id": recipient_id, "text": candidate}
            if quote_message_id:
                outbox_payload["quote_message_id"] = quote_message_id
            prepare = getattr(svc, "prepare_proactive_message", None)
            dispatch = getattr(svc, "dispatch_outbound_message", None)
            if (
                callable(prepare)
                and iscoroutinefunction(prepare)
                and callable(dispatch)
                and iscoroutinefunction(dispatch)
            ):
                pending = await prepare(
                    conv,
                    body=candidate,
                    channel=outbox_channel,
                    payload=outbox_payload,
                )
                pending_message_id = pending.id
                result = await dispatch(message_id=pending_message_id)
                if result is None:
                    result = SendOutcome(
                        ok=False, error="outbound command was not available for dispatch"
                    )
            else:
                sender = (
                    deps.zalo.for_conversation(conv)
                    if hasattr(deps.zalo, "for_conversation")
                    else deps.zalo
                )
                if provider == "facebook_messenger":
                    result = SendOutcome(
                        ok=False,
                        error="messenger requires durable outbound dispatch",
                    )
                else:
                    result = await sender.send_message(recipient_id, candidate)

    except Exception as exc:
        logger.warning("proactive turn error: conversation=%s error=%s", conv.zalo_chat_id, exc)
        result = SendOutcome(ok=False, error=str(exc))

    # 11. Persist (always — clears lock, records SENT/FAILED message,
    #     handles cadence count)
    record_kwargs = {
        "message": candidate,
        "result": result,
        "lock_owner": lock_owner,
    }
    if pending_message_id is not None:
        record_kwargs.update(
            pending_message_id=pending_message_id,
            outbox_channel=outbox_channel,
            outbox_payload=outbox_payload,
        )
    await svc.state.record_proactive_outcome(conv, **record_kwargs)
    return {"outcome": "sent" if result.ok else "send_failed", "reply": candidate}
