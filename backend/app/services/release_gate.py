"""Release-gate evaluator (Tech-Lead Directive §16 P3).

Reads the SLO service (P0-2) + golden dataset pass-rate (P3-1) and produces a
deploy/block verdict. The CI job calls ``evaluate_release_gate`` before deploy;
a regression on any enabled gate blocks the deploy with a documented reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math
from typing import Mapping
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.slo_service import SloResult, compute_slos, count_measured_runs

GateVerdict = Literal["pass", "block"]
GOLDEN_PASS_RATE_THRESHOLD_PCT = 95.0
# Below this many stage-timing measurements in the SLO window, latency/error
# rates are sample-size noise (e.g. 2 overnight runs → p95 of the two), not
# release evidence. The gate treats the SLO segment as not-evaluated instead
# of blocking; the golden correctness gate still gates.
MIN_WINDOW_RUNS = 30


class GoldenResultsError(ValueError):
    """Raised when a golden-results payload is missing or malformed."""


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
    not_evaluated: list[str]

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


def extract_golden_pass_rate(payload: Mapping[str, object]) -> float:
    """Read a golden pass-rate from an existing benchmark/result payload."""
    if "golden_pass_rate" in payload:
        raise GoldenResultsError(
            "golden_pass_rate is ambiguous; use golden_pass_rate_pct, pass_rate, "
            "or passed + case_count"
        )

    counts_keys = {"passed", "case_count"}
    counts_present = counts_keys & payload.keys()
    if counts_present and counts_present != counts_keys:
        raise GoldenResultsError("passed and case_count must be provided together")

    available_sources = [
        name
        for name, present in (
            ("golden_pass_rate_pct", "golden_pass_rate_pct" in payload),
            ("pass_rate", "pass_rate" in payload),
            ("passed_case_count", counts_present == counts_keys),
        )
        if present
    ]
    if len(available_sources) > 1:
        raise GoldenResultsError("golden results contain multiple pass-rate sources")
    if available_sources == ["golden_pass_rate_pct"]:
        return _coerce_percent(payload["golden_pass_rate_pct"], field_name="golden_pass_rate_pct")
    if available_sources == ["pass_rate"]:
        ratio = _coerce_ratio(payload["pass_rate"], field_name="pass_rate")
        return ratio * 100.0
    if available_sources == ["passed_case_count"]:
        passed = _coerce_non_negative_int(payload["passed"], field_name="passed")
        case_count = _coerce_non_negative_int(payload["case_count"], field_name="case_count")
        if case_count == 0:
            raise GoldenResultsError("case_count must be greater than zero")
        if passed > case_count:
            raise GoldenResultsError("passed must be less than or equal to case_count")
        return passed / case_count * 100.0
    raise GoldenResultsError(
        "golden results must include golden_pass_rate_pct, pass_rate, or "
        "passed + case_count"
    )


def _coerce_percent(value: object, *, field_name: str) -> float:
    numeric = _coerce_number(value, field_name=field_name)
    if numeric < 0.0 or numeric > 100.0:
        raise GoldenResultsError(f"{field_name} must be between 0 and 100 percent")
    return numeric


def _coerce_ratio(value: object, *, field_name: str) -> float:
    numeric = _coerce_number(value, field_name=field_name)
    if numeric < 0.0 or numeric > 1.0:
        raise GoldenResultsError(f"{field_name} must be a ratio between 0 and 1")
    return numeric


def _coerce_non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise GoldenResultsError(f"{field_name} must be an integer, not a boolean")
    if not isinstance(value, int):
        raise GoldenResultsError(f"{field_name} must be an integer")
    if value < 0:
        raise GoldenResultsError(f"{field_name} must be non-negative")
    return value


def _coerce_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise GoldenResultsError(f"{field_name} must be numeric, not a boolean")
    if not isinstance(value, (int, float)):
        raise GoldenResultsError(f"{field_name} must be a JSON number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise GoldenResultsError(f"{field_name} must be finite")
    return numeric


async def evaluate_release_gate(
    db: AsyncSession,
    *,
    settings,
    golden_pass_rate: float | None = None,
    window_hours: int = 24,
) -> ReleaseGateResult:
    """Evaluate retrieval-correctness + latency gates against the configured thresholds.

    ``golden_pass_rate`` is the % of golden-dataset turns (P3-1) that passed;
    None when the golden runner hasn't executed (e.g. CI skipped it).
    """
    if window_hours <= 0:
        raise ValueError("window_hours must be greater than zero")

    slos: list[SloResult] = []
    failures: list[GateFailure] = []
    not_evaluated: list[str] = []
    window_run_count: int | None = None

    if settings.release_gate_latency_slo_enabled:
        # Synthetic local-seed telemetry (stage_timings.synthetic) is demo data for
        # the performance dashboard; a release is never evaluated on it.
        window_run_count = await count_measured_runs(
            db, timedelta(hours=window_hours), exclude_synthetic=True
        )
        slos = await compute_slos(
            db, timedelta(hours=window_hours), exclude_synthetic=True
        )
    else:
        not_evaluated.append("latency_slo")

    slo_by_name = {s.name: s for s in slos}

    # Retrieval-correctness gate: golden dataset pass-rate. The controlling
    # setting keeps its historical release_gate_correctness_enabled name (it is
    # deployment surface), while the gate label names what is actually measured.
    if settings.release_gate_correctness_enabled:
        threshold = GOLDEN_PASS_RATE_THRESHOLD_PCT
        if golden_pass_rate is None:
            failures.append(
                GateFailure(
                    "retrieval_correctness",
                    None,
                    threshold,
                    "golden pass rate missing; the golden retrieval run did not produce results",
                )
            )
        elif not math.isfinite(golden_pass_rate) or golden_pass_rate < 0.0 or golden_pass_rate > 100.0:
            failures.append(
                GateFailure(
                    "retrieval_correctness",
                    None,
                    threshold,
                    "golden pass rate must be a finite percentage between 0 and 100",
                )
            )
        elif golden_pass_rate < threshold:
            failures.append(
                GateFailure(
                    "retrieval_correctness",
                    golden_pass_rate,
                    threshold,
                    f"golden pass rate {golden_pass_rate:.1f}% < {threshold}%",
                )
            )
    else:
        not_evaluated.append("retrieval_correctness")

    # Latency SLO gates.
    if settings.release_gate_latency_slo_enabled:
        if window_run_count is None or window_run_count < MIN_WINDOW_RUNS:
            not_evaluated.append(
                "latency_slo (insufficient window data: "
                f"{window_run_count} runs < {MIN_WINDOW_RUNS})"
            )
        else:
            fa = slo_by_name.get("full_answer")
            if fa is None or fa.actual_p95 is None:
                failures.append(
                    GateFailure(
                        "full_answer_p95",
                        None,
                        float(settings.release_gate_full_answer_p95_ms),
                        "full_answer p95 missing; no latency measurements available for the selected window",
                    )
                )
            elif fa.actual_p95 > settings.release_gate_full_answer_p95_ms:
                failures.append(
                    GateFailure(
                        "full_answer_p95",
                        fa.actual_p95,
                        float(settings.release_gate_full_answer_p95_ms),
                        f"full_answer p95 {fa.actual_p95:.0f}ms > {settings.release_gate_full_answer_p95_ms}ms",
                    )
                )
            err = slo_by_name.get("error_or_timeout_rate")
            if err is None or err.actual_p95 is None:
                failures.append(
                    GateFailure(
                        "error_rate",
                        None,
                        settings.release_gate_error_rate_pct,
                        "error rate missing; no error-rate measurements available for the selected window",
                    )
                )
            elif err.actual_p95 > settings.release_gate_error_rate_pct:
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
        verdict=verdict,
        failures=failures,
        slos=slos,
        golden_pass_rate=golden_pass_rate,
        not_evaluated=not_evaluated,
    )
