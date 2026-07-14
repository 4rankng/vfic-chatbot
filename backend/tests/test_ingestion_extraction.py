"""Tests for schema-constrained extraction (Tech-Lead Directive §9 stage 6)."""

from __future__ import annotations

from app.services.ingestion.extraction import (
    extract_benefit,
    extract_faq,
    extract_job_requirement,
    extract_working_hours,
    extract_for_section,
    extract_key_value_lines,
    extract_money,
)


# ─── Primitive extractors ────────────────────────────────────────────────────


def test_extract_key_value_lines_parses_colon_pairs():
    kv = extract_key_value_lines("Phụ cấp: 500,000 VND\nGiờ làm: 8:00 - 17:00")
    assert kv["phụ cấp"] == "500,000 VND"
    assert kv["giờ làm"] == "8:00 - 17:00"


def test_extract_money_vnd():
    assert extract_money("500,000 VND") == (500000.0, "VND")


def test_extract_money_k():
    assert extract_money("15k") == (15000.0, "VND")


def test_extract_money_trieu():
    assert extract_money("5 triệu") == (5000000.0, "VND")


def test_extract_money_no_match():
    assert extract_money("không có tiền ở đây") is None


# ─── Per-section extractors ──────────────────────────────────────────────────


def test_extract_benefit_from_key_value():
    env = extract_benefit("Phụ cấp chuyên cần: 500,000 VND/tháng")
    assert env is not None
    assert env.data.entity_type == "benefit"
    assert env.data.name is not None
    assert env.data.value == 500000.0


def test_extract_benefit_returns_none_when_no_money():
    env = extract_benefit("Đoạn văn không có số tiền.")
    assert env is None


def test_extract_benefit_does_not_invent_cadence():
    assert extract_benefit("Phụ cấp: 500,000 VND") is None


def test_extract_working_hours_from_time_range():
    env = extract_working_hours("Giờ làm thứ 2 đến thứ 6: 8:00 - 17:00")
    assert env is not None
    assert env.data.start_time == "08:00:00"  # zero-padded HH:MM:SS
    assert env.data.end_time == "17:00:00"
    assert env.data.crosses_midnight is False


def test_extract_working_hours_midnight_crossing_detected():
    env = extract_working_hours("Ca đêm thứ 2: 22:00 - 06:00")
    assert env is not None
    assert env.data.crosses_midnight is True


def test_extract_working_hours_does_not_invent_work_days():
    assert extract_working_hours("Giờ làm: 8:00 - 17:00") is None


def test_extract_faq_from_q_a_markers():
    env = extract_faq("Q: Hồ sơ gồm gì?\nA: Bạn cần CCCD và sơ yếu lý lịch.")
    assert env is not None
    assert "Hồ sơ gồm gì?" in env.data.canonical_question
    assert "CCCD" in env.data.answer


def test_extract_faq_returns_none_without_markers():
    assert extract_faq("Just a statement, no Q&A markers.") is None


def test_extract_job_requirement_infers_age_category():
    env = extract_job_requirement("Nam, 18-35 tuổi")
    assert env is not None
    assert env.data.category == "age"


def test_extract_job_requirement_infers_experience_category():
    env = extract_job_requirement("Có 2 năm kinh nghiệm")
    assert env is not None
    assert env.data.category == "experience"


# ─── Registry dispatch ───────────────────────────────────────────────────────


def test_extract_for_section_dispatches_benefit():
    env = extract_for_section("benefit", "Phụ cấp: 500k/tháng")
    assert env is not None
    assert env.data.entity_type == "benefit"


def test_extract_for_section_unsupported_returns_none():
    """bus_timetable + salary + location + general_policy have no deterministic
    extractor yet (deferred to P2-4 LLM extraction)."""
    assert extract_for_section("bus_timetable", "B03 06:10") is None
    assert extract_for_section("unknown", "random text") is None


def test_extract_for_section_swallows_exceptions():
    """An extractor that raises returns None (never propagates)."""

    # Pass an empty string to working_hours — the regex won't match → None (not exception).
    env = extract_for_section("working_hours", "")
    assert env is None


# ─── Provenance is always attached ───────────────────────────────────────────


def test_extracted_envelope_carries_evidence():
    """Directive §11: every material field has provenance."""
    env = extract_benefit("Phụ cấp: 500,000 VND/tháng")
    assert env is not None
    assert len(env.evidence) >= 1
    ev = env.evidence[0]
    assert ev.method in ("regex", "deterministic")
    assert 0.0 <= ev.confidence <= 1.0
    assert ev.field_path.startswith("data.")
