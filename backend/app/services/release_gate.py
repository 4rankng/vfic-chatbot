"""Release-gate evaluator (Tech-Lead Directive §16 P3).

Reads the SLO service (P0-2) + golden dataset pass-rate (P3-1) and produces a
deploy/block verdict. The CI job calls ``evaluate_release_gate`` before deploy;
a regression on any enabled gate blocks the deploy with a documented reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.slo_service import SloResult, compute_slos

GateVerdict = Literal["pass", "block"]


@dataclass(frozen=True)
class GateFailure:
    """One failing gate with the SLO/regression that triggered it."""

    gate: str
    actual: float | None
    threshold: float
    detail: str


@dataclass(frozen=True)
class ReleaseGateResult:
    """The deploy verdict + per-gate details."""

    verdict: GateVerdict
    failures: list[GateFailure]
    slos: list[SloResult]
    golden_pass_rate: float | None

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


async def evaluate_release_gate(
    db: AsyncSession,
    *,
    settings,
    golden_pass_rate: float | None = None,
    window_hours: int = 24,
) -> ReleaseGateResult:
    """Evaluate correctness + latency gates against the configured thresholds.

    ``golden_pass_rate`` is the % of golden-dataset turns (P3-1) that passed;
    None when the golden runner hasn't executed (e.g. CI skipped it).
    """
    slos = await compute_slos(db, timedelta(hours=window_hours))
    failures: list[GateFailure] = []
    slo_by_name = {s.name: s for s in slos}

    # Correctness gate: golden dataset pass-rate.
    if settings.release_gate_correctness_enabled and golden_pass_rate is not None:
        threshold = 95.0  # 95% of turns must pass
        if golden_pass_rate < threshold:
            failures.append(
                GateFailure(
                    "correctness",
                    golden_pass_rate,
                    threshold,
                    f"golden pass rate {golden_pass_rate:.1f}% < {threshold}%",
                )
            )

    # Latency SLO gates.
    if settings.release_gate_latency_slo_enabled:
        fa = slo_by_name.get("full_answer")
        if (
            fa
            and fa.actual_p95 is not None
            and fa.actual_p95 > settings.release_gate_full_answer_p95_ms
        ):
            failures.append(
                GateFailure(
                    "full_answer_p95",
                    fa.actual_p95,
                    float(settings.release_gate_full_answer_p95_ms),
                    f"full_answer p95 {fa.actual_p95:.0f}ms > {settings.release_gate_full_answer_p95_ms}ms",
                )
            )
        err = slo_by_name.get("error_or_timeout_rate")
        if (
            err
            and err.actual_p95 is not None
            and err.actual_p95 > settings.release_gate_error_rate_pct
        ):
            failures.append(
                GateFailure(
                    "error_rate",
                    err.actual_p95,
                    settings.release_gate_error_rate_pct,
                    f"error rate {err.actual_p95:.1f}% > {settings.release_gate_error_rate_pct}%",
                )
            )

    verdict: GateVerdict = "block" if failures else "pass"
    return ReleaseGateResult(
        verdict=verdict, failures=failures, slos=slos, golden_pass_rate=golden_pass_rate
    )
