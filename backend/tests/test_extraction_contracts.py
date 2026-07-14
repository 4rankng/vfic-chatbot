"""Tests for canonical extraction contracts (Tech-Lead Directive §10)."""

from __future__ import annotations

import pytest

from app.schemas.extraction_contracts import (
    BenefitEnvelopeData,
    BusStopTime,
    FaqEnvelopeData,
    Validity,
    validate_contract,
)


def _envelope(data_dict: dict, entity_type: str) -> dict:
    """Build a minimal valid envelope payload around entity data."""
    return {
        "schema_version": "1.0",
        "scope": {"type": "global"},
        "validity": {"timezone": "Asia/Ho_Chi_Minh"},
        "data": {**data_dict, "entity_type": entity_type},
        "evidence": [],
        "warnings": [],
    }


def test_faq_contract_accepts_valid_payload():
    payload = _envelope(
        {
            "canonical_question": "Tôi cần chuẩn bị hồ sơ gì?",
            "answer": "Bạn cần CCCD, sơ yếu lý lịch.",
            "language": "vi",
            "resolution_type": "static_answer",
        },
        "faq",
    )
    env = validate_contract(payload)
    assert isinstance(env.data, FaqEnvelopeData)
    assert env.data.canonical_question == "Tôi cần chuẩn bị hồ sơ gì?"


def test_faq_tool_resolution_requires_tool_name():
    payload = _envelope(
        {
            "canonical_question": "Giờ xe tiếp theo?",
            "answer": "",
            "resolution_type": "tool",
        },
        "faq",
    )
    with pytest.raises(ValueError, match="tool_name"):
        validate_contract(payload)


def test_benefit_value_requires_currency_and_cadence():
    """Directive §9: amount + currency are separate; cadence is explicit."""
    payload = _envelope(
        {"name": "Phụ cấp", "category": "ALLOWANCE", "value": 500000},
        "benefit",
    )
    with pytest.raises(ValueError, match="currency required"):
        validate_contract(payload)
    # With currency + cadence, it validates.
    payload["data"]["currency"] = "VND"
    payload["data"]["cadence"] = "monthly"
    env = validate_contract(payload)
    assert isinstance(env.data, BenefitEnvelopeData)
    assert env.data.value == 500000


def test_benefit_currency_must_be_iso_4217():
    payload = _envelope(
        {"name": "Phụ cấp", "category": "ALLOWANCE", "value": 100, "currency": "vnd", "cadence": "monthly"},
        "benefit",
    )
    with pytest.raises(ValueError):
        validate_contract(payload)


def test_working_hours_end_before_start_requires_midnight_flag():
    """Directive §9: cross-midnight shifts must be explicitly marked."""
    payload = _envelope(
        {
            "schedule_type": "SHIFT",
            "days": ["MON"],
            "start_time": "22:00:00",
            "end_time": "06:00:00",
            "crosses_midnight": False,
        },
        "working_hours",
    )
    with pytest.raises(ValueError, match="crosses_midnight"):
        validate_contract(payload)
    # With the flag set, it validates.
    payload["data"]["crosses_midnight"] = True
    env = validate_contract(payload)
    assert env.data.crosses_midnight is True


def test_working_hours_empty_days_rejected():
    payload = _envelope(
        {
            "schedule_type": "FIXED",
            "days": [],
            "start_time": "08:00:00",
            "end_time": "17:00:00",
        },
        "working_hours",
    )
    with pytest.raises(ValueError, match="days"):
        validate_contract(payload)


def test_bus_trip_stop_sequences_must_be_unique_and_ordered():
    """Directive §9: stop sequences unique and ordered within a trip."""
    payload = _envelope(
        {
            "route": {"code": "B03"},
            "service_days": ["MON"],
            "trips": [
                {
                    "stops": [
                        {"sequence": 2, "name": "B", "departure_time": "06:20:00"},
                        {"sequence": 1, "name": "A", "departure_time": "06:10:00"},
                    ]
                }
            ],
        },
        "bus_timetable",
    )
    with pytest.raises(ValueError, match="ordered"):
        validate_contract(payload)


def test_bus_stop_requires_at_least_one_time():
    with pytest.raises(ValueError, match="at least one"):
        BusStopTime(sequence=1, name="A")


def test_validity_rejects_inverted_range():
    from datetime import date

    with pytest.raises(ValueError, match="valid_from"):
        Validity(valid_from=date(2026, 7, 10), valid_to=date(2026, 7, 1))


def test_envelope_rejects_unknown_fields():
    """extra='forbid' on every model."""
    payload = _envelope(
        {"canonical_question": "Q", "answer": "A"},
        "faq",
    )
    payload["data"]["unknown_field"] = "x"
    with pytest.raises(ValueError):
        validate_contract(payload)


def test_envelope_unknown_entity_type_rejected():
    payload = _envelope(
        {"canonical_question": "Q", "answer": "A"},
        "faq",
    )
    payload["data"]["entity_type"] = "unknown_type"
    with pytest.raises(ValueError):
        validate_contract(payload)


def test_missing_data_returns_null_never_inferred():
    """Directive: 'Use null for missing data' — optional fields default to None."""
    payload = _envelope(
        {"name": "Hỗ trợ nhà ở", "category": "ACCOMMODATION"},
        "benefit",
    )
    env = validate_contract(payload)
    assert env.data.value is None
    assert env.data.currency is None
    assert env.data.cadence is None


def test_schema_version_must_match_pattern():
    payload = _envelope(
        {"canonical_question": "Q", "answer": "A"},
        "faq",
    )
    payload["schema_version"] = "1"  # invalid — needs X.Y
    with pytest.raises(ValueError):
        validate_contract(payload)
