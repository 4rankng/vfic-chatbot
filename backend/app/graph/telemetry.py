"""Per-stage wall-clock stamping for one bot turn.

Every stage helper (progressive send, claim+dispatch, the stand-down gate, and
``run_turn`` itself) records into the SAME ``timings`` dict, so the accumulator
lives here rather than in any one of them: the helpers below are pure writers
with no turn state of their own, and a turn that mixes two copies would split
``db_ms`` across both.

The dashboard contract this preserves (``app/services/reporting/``,
``app/api/performance.py``):

- ``db_ms`` is the aggregate the percentile chart reads; ``db_breakdown`` is
  the per-call map that localises a slow query.
- ``end_to_end_ms`` is candidate-visible latency from webhook receipt.
- Adapter-neutral send metrics are additive: a sender that does not provide
  telemetry simply leaves those keys out of the historical row.
"""

from __future__ import annotations

import time

from app.graph.types import BotRunState
from app.shared.application.outbound import OutboundTelemetry


def _stamp_db(timings: dict, key: str, t0: float) -> None:
    """Accumulate wall-clock of one DB call into timings['db_ms'].

    ``key`` is recorded into db_breakdown for per-call granularity when the
    dashboard needs to localize a slow query. db_ms is the aggregate the
    percentile chart reads.
    """
    elapsed = int(round((time.monotonic() - t0) * 1000))
    timings["db_ms"] = timings.get("db_ms", 0) + elapsed
    breakdown = timings.setdefault("db_breakdown", {})
    breakdown[key] = breakdown.get(key, 0) + elapsed


def _stamp_end_to_end(state: BotRunState, timings: dict | None) -> None:
    """Record candidate-visible latency from webhook receipt through completion."""
    if timings is None or state.received_at_epoch <= 0:
        return
    timings["end_to_end_ms"] = max(0, int(round((time.time() - state.received_at_epoch) * 1000)))


def _stamp_outbound_telemetry(timings: dict | None, send_result) -> None:
    """Persist adapter-neutral metrics when a sender provides them.

    Legacy fakes and non-message send paths intentionally remain valid: absence
    of telemetry is not a delivery failure and simply leaves the additive keys
    out of the historical row.
    """
    telemetry = getattr(send_result, "telemetry", None)
    if timings is not None and isinstance(telemetry, OutboundTelemetry):
        timings.update(telemetry.to_stage_timings())
