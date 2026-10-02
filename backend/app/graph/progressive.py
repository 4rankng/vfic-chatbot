"""Progressive send: shipping the first complete, useful bubble while the agent
is still generating (opt-in, agent lane only).

The agent lane streams its final answer round (``clients.MiniMaxAgent.agent`` →
``on_delta``). When the admin-managed ``llm_progressive_send`` flag is on,
``run_turn`` forwards the first complete bubble to the candidate while the rest
of the answer is still generating (measured: a sendable bubble exists at
~2.1-3.0 s against a ~8 s completion). A bubble must clear the floor, end at a
sentence boundary (never cut mid-sentence) AND carry a concrete answer signal:
a model that opens with a pleasantry must not push filler to the candidate
first. When the floor is met but the substance test fails, the sender keeps
accumulating and re-tests at each later boundary; past the wait cap it gives up
and the turn falls back to the normal single-message path.

The delivered-bubble record (``DeliveredBubble`` + ``_note_delivered_bubble``)
is load-bearing, not bookkeeping: it is written the instant ``_await_first_bubble``
dispatches, so every later terminal path finalizes THIS row and records the
bubble text instead of an empty reply that would match the SENDING row and blank
a message the candidate is already reading.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import suppress
from inspect import iscoroutinefunction
from typing import Any, NamedTuple

from app.graph.dispatch import (
    _build_outbox_payload,
    _cancel_status_task,
    _channel_for_conversation,
    _dispatch_claimed_message,
    _finalize_user_visible_reply,
    _OWNERSHIP_REFRESH_COLUMNS,
    _record_dispatched_outcome,
)
from app.graph.grounding import _UngroundedContact, ground_reply
from app.graph.ports import DirectMessageSenderPort
from app.graph.telemetry import _stamp_db, _stamp_outbound_telemetry
from app.graph.think_strip import strip_provider_artifacts, visible_offset
from app.graph.types import BotRunState, GraphDeps, TurnOutcome

logger = logging.getLogger(__name__)

# ── Progressive send (opt-in, agent lane only) ──────────────────────────────
PROGRESSIVE_BUBBLE_MIN_CHARS = 250
PROGRESSIVE_SUBSTANCE_MIN_CHARS = 80
PROGRESSIVE_MAX_WAIT_CHARS = 700
_BUBBLE_BOUNDARY_CHARS = frozenset(".!?\n…")
# "Dạ em chào anh/chị ạ." style openers, peeled from the head of a candidate
# bubble before the substance length test. The lookahead keeps a token from
# matching inside a longer word ("anh văn" peels "anh", "anhx" does not).
# Cheap and deterministic by design — the gate never spends a model call.
_GREETING_LEAD_RE = re.compile(
    r"^\s*(?:dạ|vâng|ạ|ơi|xin chào|chào|hello|hi|em|mình|tôi|bên em|anh/chị|anh|chị)"
    r"(?=$|[\s,;:.!?…/-])"
    r"[\s,;:.!?…/-]*",
    re.IGNORECASE,
)


def _next_sendable_offset(
    raw: str, *, min_offset: int = PROGRESSIVE_BUBBLE_MIN_CHARS
) -> int | None:
    """Smallest raw-stream offset >= ``min_offset`` whose prefix ends a sentence.

    The offset (not a finalized string) is the bubble boundary, so ``raw[:offset]``
    and ``raw[offset:]`` are a true prefix/suffix pair of one stream: no part of
    the answer can be sent twice, whatever the reply policy later rewrites.

    A dot between two digits is a Vietnamese thousands separator ("30.000 VND"),
    not a sentence end — cutting there splits one amount across two bubbles.

    A terminator inside unclosed parentheses ("...huyện ngoài ạ?)" — the
    observed production cut orphaned the ")") is not a boundary either: the
    parenthetical belongs to the sentence it annotates, so the bubble waits
    until the closing paren rebalances the prefix.
    """
    depth = 0
    for index, char in enumerate(raw):
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if index < min_offset - 1:
            continue
        if char not in _BUBBLE_BOUNDARY_CHARS:
            continue
        if (
            char == "."
            and 0 < index < len(raw) - 1
            and raw[index - 1].isdigit()
            and raw[index + 1].isdigit()
        ):
            continue
        if depth > 0:
            continue
        return index + 1
    return None


def _bubble_has_substance(text: str) -> bool:
    """True when a candidate bubble carries a concrete answer signal.

    Two cheap deterministic signals, no model call: a digit anywhere (salary,
    shift times, quantities, ages) or enough prose left after peeling the leading
    greeting/pleasantry run. Length alone is not enough — a bubble that is only
    the opening pleasantry must not be the candidate's first message.
    """
    if any(character.isdigit() for character in text):
        return True
    stripped = text
    while True:
        # Peel the whole leading pleasantry run, however long it is (each pass
        # strictly shortens the text, so this terminates).
        peeled = _GREETING_LEAD_RE.sub("", stripped, count=1)
        if peeled == stripped:
            break
        stripped = peeled
    return len(stripped.strip()) >= PROGRESSIVE_SUBSTANCE_MIN_CHARS


def _progressive_send_enabled(deps: GraphDeps, svc) -> bool:
    """Whether this turn may send an early bubble at all.

    Requires the admin flag AND a durable outbox dispatcher: a bubble followed by
    a remainder is terminalized through ``finalize_outbound_dispatch``, so a
    sender without it would strand a SENDING row. Absent either, the turn takes
    the pre-existing single-message path unchanged.
    """
    if not getattr(deps, "progressive_send", False):
        return False
    dispatch = getattr(svc, "dispatch_outbound_message", None)
    finalize = getattr(svc, "finalize_outbound_dispatch", None)
    return iscoroutinefunction(dispatch) and iscoroutinefunction(finalize)


class _ProgressiveStream:
    """Raw answer deltas + latest tool evidence for one progressive turn.

    ``raw`` is the single source of truth for the split (see
    ``_next_sendable_offset``). ``evidence`` mirrors what the model had actually
    been shown when the streamed text was produced, so a bubble passes the same
    grounding cross-check as a full reply.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.raw = ""
        self.evidence: list[str] = []
        self.defer_catalog = False

    async def push_delta(self, text: str) -> None:
        self.raw += text
        await self.queue.put(text)

    async def set_evidence(self, evidence: list[str]) -> None:
        self.evidence = evidence


class _EarlyBubble(NamedTuple):
    """The bubble already sent to the candidate before the lane finished."""

    text: str
    raw: str
    offset: int
    message_id: int | None
    outbox_id: int | None
    send_result: Any
    first_bubble_ms: int


class DeliveredBubble(NamedTuple):
    """A progressive early bubble that already reached (or attempted) the channel.

    Recorded on the turn state the instant ``_await_first_bubble`` dispatches it.
    Before this existed, only the success path terminalized that pair, so every
    failure path recorded the SAME ``pending_message_id`` as "nothing was sent":
    ``record_bot_outcome`` matched the SENDING row, stamped ``body = ''`` over
    the text the candidate was already reading, and the delivery-rank tie let
    the empty status win.

    ``BotRunState`` is a plain (non-slots) dataclass, so the turn state is the
    carrier: the worker reads it back after ``run_turn`` returns or raises. The
    attribute is written and read through ``setattr``/``getattr`` so the channel
    name lives in one place instead of a magic string per caller.
    """

    text: str
    message_id: int | None
    outbox_id: int | None
    ok: bool
    provider_message_id: str | None
    error: str | None
    error_class: str | None
    suppressed: bool


_DELIVERED_BUBBLE_ATTR = "delivered_bubble"


def _note_delivered_bubble(state: BotRunState, bubble: _EarlyBubble) -> DeliveredBubble:
    """Record the dispatched early bubble on the turn state."""
    send_result = bubble.send_result
    delivered = DeliveredBubble(
        text=bubble.text,
        message_id=bubble.message_id,
        outbox_id=bubble.outbox_id,
        ok=bool(send_result.ok),
        provider_message_id=getattr(send_result, "msg_id", None),
        error=None if send_result.ok else getattr(send_result, "error", None),
        error_class=None if send_result.ok else getattr(send_result, "error_class", None),
        suppressed=bool(getattr(send_result, "suppressed", False)),
    )
    setattr(state, _DELIVERED_BUBBLE_ATTR, delivered)
    return delivered


def delivered_bubble(state: Any) -> DeliveredBubble | None:
    """The early bubble this turn already delivered, if any."""
    bubble = getattr(state, _DELIVERED_BUBBLE_ATTR, None)
    return bubble if isinstance(bubble, DeliveredBubble) else None


def delivered_bubble_payload(bubble: DeliveredBubble | None) -> dict | None:
    """Plain-data form for the RQ job dict (the crash guard reads it by key)."""
    if bubble is None:
        return None
    return dict(bubble._asdict())


async def finalize_delivered_bubble(
    *,
    bubble: DeliveredBubble,
    conv,
    svc,
    timings: dict | None = None,
) -> bool:
    """Terminalize the early bubble's own outbox row before the failure record.

    Runs first so ``record_bot_outcome`` matches a row that is already terminal:
    the body it stamps is the bubble text, and the delivery-rank tie can no
    longer demote a delivered row to a suppressed one. ``telemetry=None`` keeps
    this from writing a second BotRun for the turn.

    Best-effort: a finalization failure must not stop the turn from recording
    what the candidate actually received.
    """
    if bubble.message_id is None or bubble.outbox_id is None:
        return False
    try:
        await svc.finalize_outbound_dispatch(
            conv,
            message_id=bubble.message_id,
            outbox_id=bubble.outbox_id,
            delivered=bubble.ok,
            zalo_message_id=bubble.provider_message_id,
            external_error=bubble.error,
            error_class=bubble.error_class,
            suppressed=bubble.suppressed,
            telemetry=None,
        )
    except Exception:  # noqa: BLE001 — the outcome row matters more than the outbox row
        logger.warning(
            "progressive bubble finalization failed conversation_id=%s message_id=%s",
            getattr(conv, "id", None),
            bubble.message_id,
            exc_info=True,
        )
        return False
    if timings is not None:
        timings["progressive_bubble_finalized"] = True
    return True


def _contact_evidence_text(recent_messages, user_text: str) -> str:
    """The contact-channel whitelist for a turn's reply: history + current text.

    The agent is handed the bounded chat history plus the current message, so a
    phone number or CCCD the employee typed in an *earlier* turn is text the model
    legitimately saw. Grading a bubble against the current message alone read
    those as invented channels and replaced a correct reply with the abstention
    template (seen in production on the TingTing reset flow). The system prompt
    carries no channel of its own, so the history is what was missing here.
    """
    bodies = [
        str(getattr(message, "body", "") or "").strip()
        for message in (recent_messages or [])
    ]
    return "\n".join([*[body for body in bodies if body], str(user_text or "")])


async def _await_first_bubble(
    *,
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    zalo: DirectMessageSenderPort,
    stream: _ProgressiveStream,
    lane_task: asyncio.Task,
    timings: dict,
    lock_owner: str | None,
    recipient_id: str | None,
    allowed_text: str,
    status_task,
    t0: float,
) -> _EarlyBubble | None:
    """Send the first complete, useful bubble while the agent is still generating.

    Waits for either a sendable bubble or the lane task, whichever comes first.
    Returns ``None`` on every path that must leave delivery to the existing
    whole-reply flow: the lane finished first, the answer never cleared the
    substance gate before the wait cap, the finalized bubble came out empty, or
    the claim lost. The turn then behaves exactly as it did before this feature.
    """
    min_offset = PROGRESSIVE_BUBBLE_MIN_CHARS
    rejected_for_substance = False

    def _give_up() -> None:
        """No early bubble: record why, and let the normal path deliver."""
        if rejected_for_substance:
            timings["progressive_first_bubble_skipped"] = "no_substance"

    while True:
        waiter = asyncio.ensure_future(stream.queue.get())
        try:
            await asyncio.wait({waiter, lane_task}, return_when=asyncio.FIRST_COMPLETED)
            has_delta = waiter.done()
        finally:
            if not waiter.done():
                waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await waiter
        if not has_delta:
            # The lane finished (short answer, non-agent lane, or a failure): the
            # existing path owns delivery now, whole and unchanged.
            _give_up()
            return None
        waiter.result()  # consume the delta; the accumulator already has it
        if stream.defer_catalog or any(
            str(result).partition("\n")[0].startswith("ACTIVE_PROJECT_LOOKUP_JSON=")
            for result in stream.evidence
        ):
            # A catalog answer must finish before any rows are delivered. A
            # provider cap or complete rewrite can otherwise strand the first
            # two projects with the candidate and make completeness impossible.
            timings["progressive_first_bubble_skipped"] = "catalog_completeness"
            return None
        visible_start = visible_offset(stream.raw)
        if visible_start is None:
            # The provider's think block is still open: nothing is candidate-visible
            # yet, so neither the wait cap nor the boundary search may be spent on
            # deliberation text.
            continue
        visible = stream.raw[visible_start:]
        if len(visible) > PROGRESSIVE_MAX_WAIT_CHARS:
            # Past the wait cap: stop trying so the candidate still receives the
            # complete answer as a single message.
            _give_up()
            return None
        floor = visible_start + PROGRESSIVE_BUBBLE_MIN_CHARS
        if floor > min_offset:
            min_offset = floor
        offset = _next_sendable_offset(stream.raw, min_offset=min_offset)
        if offset is None:
            continue
        bubble_raw = stream.raw[:offset]
        visible_bubble = stream.raw[visible_start:offset]
        if not _bubble_has_substance(visible_bubble):
            # Filler (greeting/pleasantry) that cleared the floor: keep
            # accumulating and re-test at the next sentence boundary.
            rejected_for_substance = True
            min_offset = offset + 1
            continue
        first_bubble_ms = int(round((time.monotonic() - t0) * 1000))
        grounded_bubble = ground_reply(
            visible_bubble,
            list(stream.evidence),
            # The same text the agent was given (history + current message):
            # a channel the employee already typed in an earlier turn is not
            # an invention, and the system prompt carries none of its own.
            allowed_text=allowed_text,
        )
        if isinstance(grounded_bubble, _UngroundedContact):
            # The bubble named a channel the evidence never had. Send nothing
            # early; the full-reply path owns the contact repair.
            logger.info(
                "progressive bubble contradicted the contact guard; deferring "
                "conversation=%s trace=%s",
                state.conversation_id,
                state.trace_id or "-",
            )
            return None
        bubble_text = _finalize_user_visible_reply(
            grounded_bubble,
            deps=deps,
            generated=True,
            user_text=state.user_text,
            timings=timings,
        )
        if not bubble_text.strip():
            # Grounding stripped the whole bubble or the reply policy found
            # nothing sendable. Send nothing; the existing path still owns the
            # turn and will apply the same policy to the complete reply.
            logger.info(
                "progressive bubble empty after grounding/policy conversation=%s trace=%s",
                state.conversation_id,
                state.trace_id or "-",
            )
            return None
        # Same pre-send guard as the normal path: refresh the ownership columns,
        # then claim the ORIGINAL placeholder row (created by record_bot_pending
        # at the top of run_turn) so no extra placeholder is created.
        db_t0 = time.monotonic()
        await deps.db.refresh(conv, _OWNERSHIP_REFRESH_COLUMNS)
        owned = await svc.claim_send(
            conv,
            version_at_start=state.version_at_start,
            lock_owner=lock_owner,
            pending_message_id=state.pending_message_id,
            reply=bubble_text,
            outbox_channel=_channel_for_conversation(conv),
            outbox_payload=_build_outbox_payload(
                recipient_id, bubble_text, state.reply_to_message_id
            ),
        )
        _stamp_db(timings, "claim_send", db_t0)
        if not owned:
            # Takeover / newer inbound / dead lock: send NOTHING and let the
            # existing stand-down path handle the turn (no partial message).
            return None
        await _cancel_status_task(status_task)
        send_t0 = time.monotonic()
        send_result = await _dispatch_claimed_message(
            svc,
            zalo,
            conv,
            message_id=state.pending_message_id,
            text=bubble_text,
            quote_message_id=state.reply_to_message_id,
        )
        timings["send_ms"] = int(round((time.monotonic() - send_t0) * 1000))
        _stamp_outbound_telemetry(timings, send_result)
        timings["progressive_send"] = True
        timings["first_bubble_ms"] = first_bubble_ms
        # Bubbles this turn's progressive path produced: 1 = the early bubble was
        # the whole answer, 2 = a remainder followed through the normal path.
        timings["progressive_bubbles"] = 1
        bubble = _EarlyBubble(
            text=bubble_text,
            raw=bubble_raw,
            offset=offset,
            message_id=state.pending_message_id,
            outbox_id=getattr(send_result, "outbox_id", None),
            send_result=send_result,
            first_bubble_ms=first_bubble_ms,
        )
        # The text is with the candidate now: every terminal path from here on
        # must finalize THIS row and record the bubble, not an empty reply.
        _note_delivered_bubble(state, bubble)
        return bubble


async def _complete_progressive_prefix(
    *,
    early: _EarlyBubble,
    stream: _ProgressiveStream,
    full_text: str,
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    timings: dict,
    lock_owner: str | None,
    recipient_id: str | None,
    allowed_text: str,
    started,
    outcome_label: str,
    faq_metadata: dict | None,
    manifest_policy,
    allow_recruitment_fast_lane: bool,
    pending_kwargs: dict,
    t0: float,
) -> tuple[str, TurnOutcome | None]:
    """Terminalize the early bubble and return what is left to send.

    ``("", outcome)`` means the early bubble was the whole answer and the turn is
    already recorded. ``(remainder_raw, None)`` means the caller must still run
    the remainder through the existing finalize → claim → dispatch path. The
    remainder is a true suffix of the raw stream by construction, so no text is
    ever sent twice.
    """
    raw_stream = stream.raw
    streamed_remainder = raw_stream[early.offset:]
    if early.raw + streamed_remainder != raw_stream:
        # Unreachable by construction (offset arithmetic). Logged, never raised:
        # a wrong split would be a data bug, not a reason to drop the turn.
        logger.error(
            "progressive split mismatch conversation=%s trace=%s",
            state.conversation_id,
            state.trace_id or "-",
        )
    visible_stream = strip_provider_artifacts(raw_stream)
    visible_prefix = strip_provider_artifacts(early.raw)
    remainder_raw = streamed_remainder
    if full_text not in (raw_stream, visible_stream):
        # The model retried or failed over mid-stream, so the streamed text is no
        # longer the text the agent returned. Never send its rejected tail:
        # preserve a verified prefix only if the final answer still starts with
        # it, otherwise deliver the complete corrected answer independently.
        # An empty final answer terminalizes only the already-delivered bubble.
        # This is alarmable, not informational:
        # it is the only place a turn records that progressive delivery and the
        # returned answer disagreed, and its frequency is the health signal for
        # mid-stream provider replacement.
        timings["progressive_stream_mismatch"] = True
        timings["progressive_stream_mismatch_chars"] = abs(
            len(raw_stream) - len(full_text)
        )
        logger.error(
            "progressive streamed text differs from the returned reply "
            "conversation=%s trace=%s streamed=%d returned=%d",
            state.conversation_id,
            state.trace_id or "-",
            len(raw_stream),
            len(full_text),
        )
        remainder_raw = (
            full_text[len(visible_prefix):]
            if visible_prefix and full_text.startswith(visible_prefix)
            else full_text
        )
    if not remainder_raw.strip() or early.outbox_id is None:
        if early.outbox_id is None:
            # Defensive: the durable-dispatcher gate makes this unreachable, but
            # without an outbox id the early row cannot be terminalized, so record
            # the bubble on its own row instead of stranding a SENDING one.
            logger.error(
                "progressive bubble has no outbox id conversation=%s trace=%s",
                state.conversation_id,
                state.trace_id or "-",
            )
        # The bubble was the whole answer (or the remainder cannot be
        # dispatched): record the turn on the bubble's own pending row — BotRun,
        # lock release, outbox final state — and send nothing more.
        outcome = await _record_dispatched_outcome(
            state=state,
            deps=deps,
            conv=conv,
            svc=svc,
            candidate=early.text,
            send_result=early.send_result,
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
        return "", outcome
    # Terminalize the early bubble now (its own message + outbox row) WITHOUT a
    # BotRun: telemetry=None keeps ``finalize_outbound_dispatch`` from writing a
    # recovery run, and the turn's single BotRun is written by the remainder's
    # record_bot_outcome below.
    db_t0 = time.monotonic()
    await svc.finalize_outbound_dispatch(
        conv,
        message_id=early.message_id,
        outbox_id=early.outbox_id,
        delivered=early.send_result.ok,
        zalo_message_id=early.send_result.msg_id,
        external_error=None if early.send_result.ok else early.send_result.error,
        error_class=early.send_result.error_class if not early.send_result.ok else None,
        suppressed=bool(getattr(early.send_result, "suppressed", False)),
        telemetry=None,
    )
    _stamp_db(timings, "finalize_outbound_dispatch", db_t0)
    # A NEW pending row for the remainder: the early bubble's row is terminal, so
    # the existing claim path needs its own placeholder to flip.
    db_t0 = time.monotonic()
    pending_msg = await svc.record_bot_pending(conv, **pending_kwargs)
    _stamp_db(timings, "record_bot_pending", db_t0)
    state.pending_message_id = pending_msg.id
    timings["progressive_bubbles"] = 2
    # Ground the remainder against the full evidence exactly as the bubble was
    # grounded: each part passes the same job-id/entity guard, independently.
    grounded_remainder = ground_reply(
        remainder_raw,
        list(stream.evidence),
        allowed_text=allowed_text,
    )
    if isinstance(grounded_remainder, _UngroundedContact):
        # A channel the evidence never had: suppress the remainder rather than
        # forward an invented contact to the candidate.
        return "", None
    return grounded_remainder, None
