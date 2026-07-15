"""Validation rules + entity resolution (Tech-Lead Directive §9 stage 7-8).

Per-domain business validators that catch semantic errors Pydantic field
validators miss (cross-field / cross-record). Plus the natural-key resolver
that dedups incoming envelopes against existing published rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.extraction_contracts import (
    BenefitEnvelopeData,
    BusTimetableData,
    ExtractionEnvelope,
    FaqEnvelopeData,
    JobRequirementEnvelopeData,
    WorkingHoursData,
)


@dataclass(frozen=True)
class ValidationIssue:
    """One validation finding (error blocks publishing; warning just flags)."""

    severity: str  # "error" | "warning"
    code: str
    message: str
    field_path: str | None = None


def validate_envelope(envelope: ExtractionEnvelope) -> list[ValidationIssue]:
    """Run business-rule validators per entity type. Returns issues (may be empty).

    Errors block publishing (caller transitions to REVIEW_REQUIRED); warnings
    are surfaced but non-blocking.
    """
    data = envelope.data
    # Dispatch on entity_type string so the validator works both with real
    # Pydantic envelopes AND test doubles (SimpleNamespace).
    et = getattr(data, "entity_type", None)
    if et == "benefit":
        return _validate_benefit(data)
    if et == "working_hours":
        return _validate_working_hours(data)
    if et == "bus_timetable":
        return _validate_bus_timetable(data)
    if et == "faq":
        return _validate_faq(data)
    if et == "job_requirement":
        return _validate_job_requirement(data)
    return []


def _validate_benefit(data: BenefitEnvelopeData) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # Directive §9 benefits rules: amount + currency separate, cadence explicit.
    if data.value is not None and data.currency is None:
        issues.append(
            ValidationIssue(
                "error", "missing_currency", "value set but currency missing", "data.currency"
            )
        )
    if data.value is not None and data.cadence is None:
        issues.append(
            ValidationIssue(
                "error", "missing_cadence", "value set but cadence missing", "data.cadence"
            )
        )
    if data.value is not None and data.value < 0:
        issues.append(
            ValidationIssue("error", "negative_value", "benefit value negative", "data.value")
        )
    if (
        data.eligibility
        and any(c.isdigit() for c in data.eligibility)
        and "VND" in data.eligibility
    ):
        issues.append(
            ValidationIssue(
                "warning",
                "money_in_eligibility",
                "eligibility field may contain an amount",
                "data.eligibility",
            )
        )
    return issues


def _validate_working_hours(data: WorkingHoursData) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # Directive §9: cross-midnight must be explicit.
    if data.start_time and data.end_time:
        if data.end_time <= data.start_time and not data.crosses_midnight:
            issues.append(
                ValidationIssue(
                    "error",
                    "crosses_midnight_required",
                    "end ≤ start requires crosses_midnight=True",
                    "data.crosses_midnight",
                )
            )
    # Directive §9: days of week valid (Pydantic enforces the Literal; just check non-empty).
    if not data.days:
        issues.append(ValidationIssue("error", "empty_days", "days list empty", "data.days"))
    return issues


def _validate_bus_timetable(data: BusTimetableData) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # Directive §9: times non-decreasing within a trip (modulo midnight).
    for i, trip in enumerate(data.trips):
        prev_time: str | None = None
        for stop in trip.stops:
            t = stop.departure_time or stop.arrival_time
            if t and prev_time and t < prev_time:
                # Could be a midnight crossing; flag as warning for review.
                issues.append(
                    ValidationIssue(
                        "warning",
                        "time_decrease",
                        f"trip[{i}] time decreased {prev_time} → {t}",
                        f"data.trips[{i}]",
                    )
                )
            if t:
                prev_time = t
    return issues


def _validate_faq(data: FaqEnvelopeData) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # Directive §9: dynamic questions reference a tool, not duplicate facts.
    if data.resolution_type == "static_answer" and not data.answer:
        issues.append(
            ValidationIssue(
                "error", "empty_answer", "static_answer requires non-empty answer", "data.answer"
            )
        )
    return issues


def _validate_job_requirement(data: JobRequirementEnvelopeData) -> list[ValidationIssue]:
    # Requirements are free-text; minimal validation.
    return []


# ─── Natural-key resolution (directive §8) ───────────────────────────────────


def natural_key_for(envelope: ExtractionEnvelope) -> tuple:
    """Return the natural key tuple for dedup. Matches the publishing service."""
    data = envelope.data
    scope = envelope.scope
    et = getattr(data, "entity_type", None)
    if et == "faq":
        return ("faq", scope.type, _norm(data.canonical_question))
    if et == "benefit":
        return ("benefit", scope.type, _norm(data.name))
    if et == "job_requirement":
        return ("job_requirement", _norm(data.text))
    if et == "working_hours":
        return (
            "working_hours",
            scope.type,
            tuple(sorted(data.days)),
            data.start_time,
            data.end_time,
        )
    return (et,)


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def has_blocking_errors(issues: list[ValidationIssue]) -> bool:
    """True if any issue is severity='error' (should block auto-publish)."""
    return any(i.severity == "error" for i in issues)
