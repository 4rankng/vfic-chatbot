"""Tests for validation rules + entity resolution (Tech-Lead Directive §9).

The Pydantic contracts already enforce field-level rules (value ≥ 0, currency
required when value set, etc.). These tests cover the BUSINESS-rule layer that
operates on already-validated envelopes — cross-field checks the contracts miss
and the natural-key resolver.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.ingestion.validation import (
    ValidationIssue,
    has_blocking_errors,
    natural_key_for,
    validate_envelope,
)


def _make_benefit_envelope(value=None, currency=None, cadence=None, eligibility=None):
    """Construct a BenefitEnvelopeData-like object bypassing Pydantic so we can
    test business rules the contracts already enforce (negative value etc.)."""
    data = SimpleNamespace(
        entity_type="benefit",
        name="Phụ cấp",
        category="ALLOWANCE",
        value=value,
        currency=currency,
        cadence=cadence,
        eligibility=eligibility,
        taxable=None,
    )
    return SimpleNamespace(
        schema_version="1.0",
        scope=SimpleNamespace(type="global", id=None),
        validity=SimpleNamespace(valid_from=None, valid_to=None, timezone="Asia/Ho_Chi_Minh"),
        data=data,
        evidence=[],
        warnings=[],
    )


def _make_working_hours_envelope(start="08:00:00", end="17:00:00", crosses=False, days=None):
    data = SimpleNamespace(
        entity_type="working_hours",
        schedule_type="FIXED",
        days=days if days is not None else ["MON"],
        start_time=start,
        end_time=end,
        crosses_midnight=crosses,
        breaks=[],
        exceptions=[],
    )
    return SimpleNamespace(
        schema_version="1.0",
        scope=SimpleNamespace(type="global", id=None),
        validity=SimpleNamespace(valid_from=None, valid_to=None, timezone="Asia/Ho_Chi_Minh"),
        data=data,
        evidence=[],
        warnings=[],
    )


def test_validate_benefit_negative_value_blocks():
    """The business validator catches negative value (Pydantic also catches it,
    but the validator layer is defense-in-depth)."""
    env = _make_benefit_envelope(value=-100, currency="VND", cadence="monthly")
    issues = validate_envelope(env)
    assert any(i.code == "negative_value" and i.severity == "error" for i in issues)


def test_validate_benefit_money_in_eligibility_warns():
    """Directive §9: eligibility should not mix in amounts."""
    env = _make_benefit_envelope(value=500000, currency="VND", cadence="monthly", eligibility="500 VND nếu đủ công")
    issues = validate_envelope(env)
    assert any(i.code == "money_in_eligibility" and i.severity == "warning" for i in issues)


def test_validate_benefit_complete_passes():
    env = _make_benefit_envelope(value=500000, currency="VND", cadence="monthly")
    issues = validate_envelope(env)
    assert not has_blocking_errors(issues)


def test_validate_working_hours_crosses_midnight_required():
    """end ≤ start without crosses_midnight=True is an error."""
    env = _make_working_hours_envelope(start="22:00:00", end="06:00:00", crosses=False)
    issues = validate_envelope(env)
    assert any(i.code == "crosses_midnight_required" and i.severity == "error" for i in issues)


def test_validate_working_hours_empty_days_blocks():
    env = _make_working_hours_envelope(days=[])
    issues = validate_envelope(env)
    assert any(i.code == "empty_days" and i.severity == "error" for i in issues)


def test_has_blocking_errors_detects_error_severity():
    issues = [ValidationIssue("warning", "w", "..."), ValidationIssue("error", "e", "...")]
    assert has_blocking_errors(issues) is True


def test_has_blocking_errors_false_when_only_warnings():
    issues = [ValidationIssue("warning", "w", "...")]
    assert has_blocking_errors(issues) is False


def test_natural_key_faq_uses_normalized_question():
    data = SimpleNamespace(entity_type="faq", canonical_question="Hồ Sơ Gì", answer="A")
    env = SimpleNamespace(
        scope=SimpleNamespace(type="global", id=None), data=data
    )
    nk = natural_key_for(env)
    assert nk == ("faq", "global", "hồ sơ gì")


def test_natural_key_benefit_uses_name():
    data = SimpleNamespace(entity_type="benefit", name="Phụ Cấp Chuyên Cần")
    env = SimpleNamespace(
        scope=SimpleNamespace(type="job_posting", id="job-1"), data=data
    )
    nk = natural_key_for(env)
    assert nk == ("benefit", "job_posting", "phụ cấp chuyên cần")
