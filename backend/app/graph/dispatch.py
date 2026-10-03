"""Outbound side of a turn: the typing indicator, the pre-send guard, and the
atomic claim -> send -> record unit.

This is the only module that touches the transport. It owns:

- the channel identity reads (``_channel_for_conversation`` /
  ``_recipient_for_conversation``) every other stage needs to describe the same
  conversation the same way;
- the column-scoped ownership refresh that both claim sites perform
  (``_OWNERSHIP_REFRESH_COLUMNS``) — the guard is the claim's contract, so the
  column list belongs with the claim, not with the stand-down gate;
- the typing heartbeat and its cancel, because the cancel is a send boundary
  (every real send stops the indicator first);
- ``_finalize_user_visible_reply``, the converged content boundary: what goes on
  the wire is stripped of provider thinking artifacts and shipped as-is, and the
  progressive path applies the exact same boundary to a bubble.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from inspect import iscoroutinefunction
from typing import Any

from app.conversation_messaging.domain.delivery import DeliveryState
from app.graph.chat_status import native_status_heartbeat
from app.graph.ports import (
    ChatStatusSenderPort,
    DeliveryResultPort,
    DirectMessageSenderPort,
    SendOutcome,
)
from app.graph.telemetry import (
    _stamp_db,
    _stamp_end_to_end,
    _stamp_outbound_telemetry,
)
from app.graph.think_strip import (
    contains_tool_protocol,
    strip_markdown_decorations,
    strip_provider_artifacts,
)
from app.graph.types import BotRunState, GraphDeps, TurnOutcome
from app.recruitment.domain.provider import (
    provider_from_conversation,
    recipient_from_conversation,
)
from app.shared.application.outbound import AMBIGUOUS_SEND_CLASSES, is_ambiguous_send

logger = logging.getLogger(__name__)

# The ownership bookkeeping columns a pre-send refresh must reload (recheck +
# claim). A full ``db.refresh(conv)`` also re-fetches the ``contact`` and
# ``channel_identity`` selectin relationships — 3–4 extra SELECTs per refresh,
# twice per turn — while the ownership recheck (bot_path.recheck_ownership)
# reads only these columns and the claim's authority is its server-side
# ``WHERE EXISTS``. Keep the list exhaustive for everything the recheck reads
# (``taken_over_at``/``updated_at`` feed the semi-auto guard) or a takeover
# could again slip past a stale identity-map snapshot.
_OWNERSHIP_REFRESH_COLUMNS = [
    "version",
    "mode",
    "status",
    "taken_over_at",
    "updated_at",
    "bot_lock_owner",
    "bot_locked_until",
    "bot_lock_heartbeat_at",
]


def _channel_for_conversation(conv) -> str:
    """Return the persisted delivery channel, never inferring it from a wrapper."""
    return provider_from_conversation(conv)


def _recipient_for_conversation(conv) -> str | None:
    """Return the immutable provider recipient used by the outbound command."""
    return recipient_from_conversation(conv)


def _finalize_user_visible_reply(
    raw: str,
    *,
    deps: GraphDeps,
    generated: bool,
    user_text: str,
    timings: dict,
) -> str:
    """Converged reply boundary: strip provider artefacts, or refuse the reply.

    ``deps``/``generated``/``user_text`` stay in the signature so the
    progressive-send bubble and the full-answer call site keep one boundary shape.

    Generated answers are LLM prose bound for a plain-text channel (Zalo): any
    markdown the model wrapped around the answer reaches the candidate as
    literal asterisks/ticks, so decorations are stripped deterministically
    (the persona forbids markdown; this is the backstop). Curated replies keep
    their authored formatting untouched.

    The same boundary owns protocol residue: stripping markdown is lossless, but
    a provider that serialized a tool call into its content may write a format
    the parsers do not know. Generated text that still carries tool-call protocol
    after the strip is not an answer, so this returns "" and every caller takes
    its existing empty-candidate path. Only generated text is guarded — curated
    and tool-authored replies are DB content that may legitimately hold angle
    brackets.
    """
    stripped = strip_provider_artifacts(raw)
    if not generated:
        return stripped
    cleaned = strip_markdown_decorations(stripped)
    # A parser that misses is recoverable; a stripper that misses is not. If
    # protocol markup survived the strip it is not a reply: return nothing so
    # every caller takes its existing empty-candidate path — runner suppresses
    # the turn, the progressive bubble defers to the whole-reply path.
    if contains_tool_protocol(cleaned):
        return ""
    return cleaned


def _build_outbox_payload(
    chat_id: str | None, text: str, quote_message_id: str | None
) -> dict:
    """Build the provider send payload recorded in the outbox.

    Captures the exact body sent to the provider so a re-dispatch (from the sweep) can
    reconstruct the call without re-running the turn. ``quote_message_id`` is
    the OA CS-reply field (None on the Bot channel).
    """
    payload: dict = {"chat_id": chat_id, "text": text}
    if quote_message_id:
        payload["quote_message_id"] = quote_message_id
    return payload


async def _dispatch_claimed_message(
    svc,
    zalo: DirectMessageSenderPort,
    conv,
    *,
    message_id: int | None,
    text: str,
    quote_message_id: str | None,
) -> DeliveryResultPort:
    """Send an already-persisted command, retaining fake-port compatibility."""
    dispatch = getattr(svc, "dispatch_outbound_message", None)
    if callable(dispatch) and iscoroutinefunction(dispatch):
        result = await dispatch(message_id=message_id)
        if result is not None:
            return result
        return SendOutcome(
            ok=False,
            error="outbound command was not available for dispatch",
        )
    if _channel_for_conversation(conv) == "facebook_messenger":
        return SendOutcome(
            ok=False,
            error="messenger requires durable outbound dispatch",
        )
    recipient_id = _recipient_for_conversation(conv)
    if not recipient_id:
        # A Zalo conversation always carries its chat id; this guard keeps a row
        # that somehow lost it from being handed to the provider as ``None``.
        return SendOutcome(
            ok=False,
            error="conversation has no provider recipient",
        )
    if quote_message_id:
        return await zalo.send_message(recipient_id, text, quote_message_id=quote_message_id)
    return await zalo.send_message(recipient_id, text)


def _delivery_status_for_send_error(
    error_class: str | None,
    *,
    ok: bool,
    send_unknown: Any,
):
    return send_unknown if is_ambiguous_send(error_class, ok=ok) else None


def _delivery_statuses(deps: GraphDeps):
    if deps.delivery_statuses is not None:
        return deps.delivery_statuses

    class _NeutralDeliveryStatuses:
        suppressed = DeliveryState.SUPPRESSED
        send_unknown = DeliveryState.SEND_UNKNOWN

    return _NeutralDeliveryStatuses()


async def _status_heartbeat(zalo: ChatStatusSenderPort, chat_id: str, *, settings) -> None:
    """Pulse supported native status until the turn owner drains this task."""
    await native_status_heartbeat(
        lambda: zalo.send_chat_action(chat_id, "typing"),
        interval_seconds=settings.typing_heartbeat_seconds,
    )


async def _cancel_status_task(task) -> None:
    """Cancel the status heartbeat and drain it so no ack lands after the real send."""
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _claim_and_dispatch(
    *,
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    zalo: DirectMessageSenderPort,
    candidate: str,
    timings: dict,
    started,
    lock_owner: str | None,
    status_task,
    recipient_id: str | None,
    outcome_label: str,
    faq_metadata: dict | None,
    manifest_policy,
    allow_recruitment_fast_lane: bool,
    t0: float,
) -> TurnOutcome | None:
    """Claim the send atomically, and when owned, dispatch and record as one unit.

    Returns the turn's final outcome mapping when the claim won; ``None`` when
    the claim lost (a takeover or newer inbound bumped the version) and the
    caller must stand the turn down through ``_authority_gate``.
    """
    # --- pre_send_guard: atomically claim the send (PENDING→SENDING), gated
    # server-side on version + lock_owner + lock liveness. Closes both the
    # crash-window (a stale SENDING row left by a post-send crash is reconciled
    # as sent-but-unconfirmed, at-most-once) and the recheck→send TOCTOU (a
    # takeover or newer inbound bumping version before the claim yields rowcount
    # 0 → suppress). A column-scoped refresh() keeps the bound conv's ownership
    # columns on committed state without re-fetching the selectin cascade. ---
    db_t0 = time.monotonic()
    await deps.db.refresh(conv, _OWNERSHIP_REFRESH_COLUMNS)
    owned = await svc.claim_send(
        conv,
        version_at_start=state.version_at_start,
        lock_owner=lock_owner,
        pending_message_id=state.pending_message_id,
        reply=candidate,
        outbox_channel=_channel_for_conversation(conv),
        outbox_payload=_build_outbox_payload(
            recipient_id, candidate, state.reply_to_message_id
        ),
    )
    _stamp_db(timings, "claim_send", db_t0)
    if not owned:
        return None

    await _cancel_status_task(status_task)
    send_t0 = time.monotonic()
    send_result = await _dispatch_claimed_message(
        svc,
        zalo,
        conv,
        message_id=state.pending_message_id,
        text=candidate,
        quote_message_id=state.reply_to_message_id,
    )
    timings["send_ms"] = round((time.monotonic() - send_t0) * 1000)
    _stamp_outbound_telemetry(timings, send_result)
    return await _record_dispatched_outcome(
        state=state,
        deps=deps,
        conv=conv,
        svc=svc,
        candidate=candidate,
        send_result=send_result,
        timings=timings,
        started=started,
        lock_owner=lock_owner,
        recipient_id=recipient_id,
        outcome_label=outcome_label,
        faq_metadata=faq_metadata,
        manifest_policy=manifest_policy,
        allow_recruitment_fast_lane=allow_recruitment_fast_lane,
        t0=t0,
    )


async def _record_dispatched_outcome(
    *,
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    candidate: str,
    send_result,
    timings: dict,
    started,
    lock_owner: str | None,
    recipient_id: str | None,
    outcome_label: str,
    faq_metadata: dict | None,
    manifest_policy,
    allow_recruitment_fast_lane: bool,
    t0: float,
) -> TurnOutcome:
    """Record an already-dispatched candidate: BotRun, message, outbox, lock.

    Shared by the normal claim→send→record tail and the progressive path's
    already-sent bubble, so the delivery classification and the audit row cannot
    drift between the two.
    """
    timings["total_ms"] = round((time.monotonic() - t0) * 1000)
    _stamp_end_to_end(state, timings)
    db_t0 = time.monotonic()
    # Classify transport failures: ambiguous (timeout/reset after the
    # request may have reached Zalo) → SEND_UNKNOWN (non-retriable); every
    # other failure stays FAILED (the reconciler may re-enqueue).
    send_suppressed = bool(getattr(send_result, "suppressed", False))
    send_error_class = send_result.error_class if not send_result.ok else None
    statuses = _delivery_statuses(deps)
    override_status: Any | None = None
    if send_suppressed:
        override_status = statuses.suppressed
    elif send_error_class in AMBIGUOUS_SEND_CLASSES:
        override_status = statuses.send_unknown
    await svc.record_bot_outcome(
        conv,
        version_at_start=state.version_at_start,
        reply=candidate,
        started_at=started,
        sent=send_result.ok,
        pending_message_id=state.pending_message_id,
        external_error=None if send_result.ok else send_result.error,
        zalo_message_id=send_result.msg_id,
        stage_timings=timings,
        lock_owner=lock_owner,
        delivery_status=override_status,
        trace_id=state.trace_id or None,
        outcome_metadata=faq_metadata,
        outbox_channel=_channel_for_conversation(conv),
        outbox_payload=_build_outbox_payload(
            recipient_id, candidate, state.reply_to_message_id
        ),
    )
    _stamp_db(timings, "record_bot_outcome", db_t0)
    if send_suppressed:
        return {"outcome": "suppressed", "reason": send_result.error, "reply": candidate}
    if not send_result.ok:
        return {
            "outcome": (
                "send_unknown"
                if override_status is statuses.send_unknown
                else "send_failed"
            ),
            "reason": send_result.error,
            "reply": candidate,
        }
    # The post-send extraction owns lead, memory, and contact intent. Every
    # LLM-generated turn is eligible for recruitment extraction.
    # Candidate extraction owns recruitment lead/contact state. It is
    # not a generic post-send hook, so never enqueue it for a
    # manifest-composed non-recruitment installation.
    if deps.persist is not None and allow_recruitment_fast_lane:
        persist_job = {
            "chat_id": recipient_id,
            "user_text": state.user_text,
            "bot_output": candidate,
            "conversation_version": state.version_at_start,
            "contact_id": str(conv.contact_id) if conv.contact_id else None,
            "conversation_id": str(conv.id),
        }
        if manifest_policy is not None:
            persist_job.update(
                {
                    "runtime_revision_id": manifest_policy.revision_id,
                    "authority_generation": state.authority_generation,
                    "runtime_fingerprint": manifest_policy.fingerprint_checksum,
                }
            )
        deps.persist(persist_job)
    return {"outcome": outcome_label, "reply": candidate}
