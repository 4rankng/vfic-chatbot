"""The stand-down exit: every turn that must not speak funnels through here.

Two depths share one teardown (see ``_authority_gate``):

- Pre-pending guard (``started`` None): the turn never created its pending row
  or typing heartbeat, so the gate only releases the per-chat lock and writes no
  outcome row at all.
- Silent terminal (``reply`` None): the bot had nothing to send — the audit row
  stays empty via ``_record_silent_terminal``.
- Lost-claim terminal (``reply`` set): the drafted candidate was never sent (the
  claim lost) but is still recorded, sent=False, for the audit trail.

The silent terminal is the path REL-13 made load-bearing: when progressive send
already put a bubble with the candidate, that bubble IS this turn's answer, so
the bubble's outbox row is finalized BEFORE the outcome is recorded and the
outcome carries the bubble text with ``sent=send_result.ok``. Recording
``reply=''`` against the same ``pending_message_id`` would match the bubble's own
row and blank a message the candidate is already reading.
"""

from __future__ import annotations

import time

from app.graph.dispatch import _cancel_status_task
from app.graph.progressive import delivered_bubble, finalize_delivered_bubble
from app.graph.telemetry import _stamp_db, _stamp_end_to_end
from app.graph.types import BotRunState, GraphDeps, TurnOutcome


async def _record_silent_terminal(
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    started,
    base_outcome: str,
    *,
    stage_timings: dict | None = None,
    trace_sink=None,
    lock_owner=None,
) -> TurnOutcome:
    """Record a turn that produced no answer — and send nothing more to the customer.

    The silent terminal path: when the bot cannot produce
    an answer (agent crash, exhausted provider chain), an error text would read
    as a broken bot and leak internals, so the turn goes quiet. The outcome is
    SUPPRESSED so the per-chat mutex clears and the dashboard keeps the
    degraded-turn audit row; the failure lives in the structured logs instead.

    "Nothing more" is literal. When progressive send already put a bubble with
    the candidate, that bubble IS this turn's answer: its outbox row is
    finalized first and the outcome records the bubble text with
    ``sent=send_result.ok``. Recording ``reply=''`` against the same
    ``pending_message_id`` would match the bubble's own row and blank a message
    the candidate is already reading.
    """
    _stamp_end_to_end(state, stage_timings)
    bubble = delivered_bubble(state)
    if bubble is not None:
        await finalize_delivered_bubble(
            bubble=bubble, conv=conv, svc=svc, timings=stage_timings
        )
    await svc.record_bot_outcome(
        conv,
        version_at_start=state.version_at_start,
        reply=bubble.text if bubble is not None else "",
        started_at=started,
        sent=bubble.ok if bubble is not None else False,
        pending_message_id=(
            bubble.message_id if bubble is not None else state.pending_message_id
        ),
        external_error=bubble.error if bubble is not None else None,
        zalo_message_id=bubble.provider_message_id if bubble is not None else None,
        stage_timings=stage_timings,
        lock_owner=lock_owner,
        trace_id=state.trace_id or None,
        decision_trace=trace_sink.snapshot_payload() if trace_sink is not None else None,
    )
    return {"outcome": base_outcome, "reply": bubble.text if bubble is not None else ""}


async def _authority_gate(
    *,
    state: BotRunState,
    deps: GraphDeps,
    conv,
    svc,
    reason: str,
    lock_owner: str | None = None,
    started=None,
    timings: dict | None = None,
    trace_sink=None,
    status_task=None,
    reply: str | None = None,
    outcome_metadata: dict | None = None,
    refresh_conv: bool = False,
) -> TurnOutcome:
    """The single stand-down exit for a turn denied authority or ownership.

    Every suppressed-classed exit funnels here so the teardown exists in one
    place. Three stand-down depths share the gate:

    - Pre-pending guard (``started`` None): the turn never created its pending
      row or typing heartbeat, so the gate releases the per-chat lock and
      returns without writing an outcome row.
    - Silent terminal (``reply`` None): the bot had nothing to send; the audit
      row stays empty via ``_record_silent_terminal``.
    - Lost-claim terminal (``reply`` set): the drafted candidate was never sent
      (the claim lost) but is still recorded, sent=False, for the audit trail.

    ``refresh_conv`` mirrors the pre-existing call shapes: the agent-error and
    empty-candidate terminals refresh the bound conversation onto committed
    state before recording, while the lost-claim terminal relies on the
    refresh that immediately precedes ``claim_send``.
    """
    if status_task is not None:
        await _cancel_status_task(status_task)
    if started is None:
        if lock_owner:
            await svc.release_lock(conv, lock_owner=lock_owner)
        return {"outcome": "suppressed", "reason": reason}
    if refresh_conv:
        await deps.db.refresh(conv)
    if trace_sink is not None:
        trace_sink.record_decision("ownership_verdict", "suppressed")
    if reply is None:
        return await _record_silent_terminal(
            state, deps, conv, svc, started, reason,
            stage_timings=timings,
            trace_sink=trace_sink,
            lock_owner=lock_owner,
        )
    decision_trace = trace_sink.snapshot_payload() if trace_sink is not None else None
    db_t0 = time.monotonic()
    await svc.record_bot_outcome(
        conv,
        version_at_start=state.version_at_start,
        reply=reply,
        started_at=started,
        sent=False,
        pending_message_id=state.pending_message_id,
        stage_timings=timings,
        lock_owner=lock_owner,
        trace_id=state.trace_id or None,
        outcome_metadata=outcome_metadata,
        decision_trace=decision_trace,
    )
    _stamp_db(timings, "record_bot_outcome", db_t0)
    return {"outcome": reason, "reply": reply}
