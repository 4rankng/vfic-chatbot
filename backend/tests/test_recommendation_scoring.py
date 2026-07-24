"""Tests for the structured Job↔Lead recommendation scoring engine (Phase 2).

The scorer is pure Python (no DB, no LLM) so every signal is pinned in isolation.
Repository-level hard filters are covered by the tool test's fake-retrieval path.
"""

from __future__ import annotations

from app.recruitment.domain.recommendation import is_salary_profile_statement
from app.services.recommendation.scoring import (
    JobCandidate,
    LeadProfile,
    parse_salary_band,
    score_job,
)


# --- parse_salary_band -------------------------------------------------------


def test_parse_salary_band_single_trieu():
    assert parse_salary_band("12 triệu") == (9_600_000, 12_000_000)


def test_parse_salary_band_range_trieu():
    assert parse_salary_band("10-15 triệu") == (10_000_000, 15_000_000)


def test_parse_salary_band_plain_vnd():
    lo, hi = parse_salary_band("20000000")
    assert lo == 16_000_000
    assert hi == 20_000_000


def test_parse_salary_band_accented_vietnamese():
    # normalize_vietnamese_text strips diacritics before matching.
    assert parse_salary_band("12 triệu") == (9_600_000, 12_000_000)


def test_parse_salary_band_none_when_unparseable():
    assert parse_salary_band(None) == (None, None)
    assert parse_salary_band("") == (None, None)
    assert parse_salary_band("thỏa thuận") == (None, None)
    assert parse_salary_band(f"{'9' * 400} triệu") == (None, None)


def test_salary_profile_statement_is_not_a_project_comparison():
    statements = (
        "Lương mong muốn của em là 20 triệu",
        "Em đang nhận lương 20 triệu",
        "Thu nhập hiện tại của em là 15 triệu",
    )

    assert all(is_salary_profile_statement(text) for text in statements)


# --- LeadProfile.from_lead ---------------------------------------------------


def test_lead_profile_from_lead_extracts_signals():
    lead = {
        "desired_job": "kho vận",
        "living_area": "Bình Dương",
        "expected_salary": "12 triệu",
        "age": 25,
    }
    profile = LeadProfile.from_lead(lead)
    assert profile.desired_job == "kho vận"
    assert profile.salary_min == 9_600_000
    assert profile.salary_max == 12_000_000
    assert profile.has_any_signal


def test_lead_profile_empty_lead_has_no_signal():
    profile = LeadProfile.from_lead(None)
    assert not profile.has_any_signal


# --- score_job ---------------------------------------------------------------


def _job(**kw) -> JobCandidate:
    base = {
        "id": "job-1",
        "title": "Nhân viên kho",
        "province": "Bình Dương",
        "salary_min": 10_000_000,
        "salary_max": 14_000_000,
        "experience_required": "",
    }
    base.update(kw)
    return JobCandidate.from_row(base)


def test_score_job_full_match_scores_high_with_reasons():
    lead = LeadProfile.from_lead(
        {"desired_job": "nhân viên kho", "living_area": "Bình Dương", "expected_salary": "12 triệu"}
    )
    result = score_job(lead, _job())
    assert result.score > 0.5
    assert any("vị trí" in r for r in result.reasons)
    assert any("lương" in r for r in result.reasons)
    assert any("khu vực" in r for r in result.reasons)


def test_score_job_salary_mismatch_zero_salary_signal():
    """A job paying below the candidate's floor gets zero salary score."""
    lead = LeadProfile.from_lead({"expected_salary": "20 triệu"})
    job = _job(salary_min=8_000_000, salary_max=10_000_000)
    result = score_job(lead, job)
    # salary contributes 0, but other signals may still fire; just check no salary reason.
    assert not any("lương" in r and "phù hợp" in r for r in result.reasons)


def test_score_job_wrong_province_scores_zero_location():
    lead = LeadProfile.from_lead({"desired_job": "kho", "living_area": "Hà Nội"})
    job = _job(province="Bình Dương")
    result = score_job(lead, job)
    assert not any("khu vực" in r for r in result.reasons)


def test_score_job_no_experience_required_surfaces_as_reason():
    lead = LeadProfile.from_lead({"desired_job": "kho"})
    job = _job(experience_required="Không yêu cầu kinh nghiệm")
    result = score_job(lead, job)
    assert any("không yêu cầu kinh nghiệm" in r for r in result.reasons)


def test_score_job_orders_by_score_desc():
    """Multiple jobs sort by total score descending."""
    lead = LeadProfile.from_lead(
        {"desired_job": "nhân viên kho", "living_area": "Bình Dương", "expected_salary": "12 triệu"}
    )
    strong = score_job(lead, _job(id="strong"))
    weak = score_job(
        lead,
        _job(
            id="weak",
            title="Lái xe",  # no title overlap
            province="Đồng Nai",  # no location overlap
        ),
    )
    assert strong.score > weak.score


def test_score_job_empty_reasons_falls_back_to_generic():
    """A job with no matching signals still gets a generic 'việc làm đang tuyển' reason."""
    lead = LeadProfile.from_lead({"desired_job": "lập trình"})
    result = score_job(lead, _job(title="Nhân viên kho"))
    assert result.reasons == ["việc làm đang tuyển"]
