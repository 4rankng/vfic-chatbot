"""Tests for the search projector + review bundle service."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.ingestion.projector import (
    project_benefit,
    project_faq,
    project_job_requirement,
    project_row,
    project_working_hours,
    projections_for_batch,
)
from app.services.ingestion.review_service import (
    CRITICAL_FIELDS,
    REVIEW_OUTCOMES,
    classify_outcome,
)
from app.services.ingestion.validation import ValidationIssue


# ─── Projector ───────────────────────────────────────────────────────────────


def test_project_benefit_renders_vietnamese_text():
    row = SimpleNamespace(
        id=1,
        name="Phụ cấp chuyên cần",
        scope_type="job_posting",
        value=500000,
        currency="VND",
        cadence="monthly",
        eligibility="Đủ ngày công",
    )
    p = project_benefit(row)
    assert p.entity_type == "benefit"
    assert p.section_type == "benefit"
    assert "Phụ cấp chuyên cần" in p.rendered_text
    assert "500,000 VND/monthly" in p.rendered_text
    assert p.structured_payload["value"] == 500000


def test_project_working_hours_renders_time_range():
    row = SimpleNamespace(
        id=2,
        scope_type="company",
        start_time="08:00:00",
        end_time="17:00:00",
        days=["MON", "TUE"],
        crosses_midnight=False,
    )
    p = project_working_hours(row)
    assert "08:00:00" in p.rendered_text
    assert "17:00:00" in p.rendered_text
    assert "MON" in p.rendered_text


def test_project_faq_renders_question_plus_answer():
    row = SimpleNamespace(
        id=3,
        scope_type="global",
        canonical_question="Hồ sơ gồm gì?",
        answer="Bạn cần CCCD.",
        language="vi",
        resolution_type="static_answer",
    )
    p = project_faq(row)
    assert "Hồ sơ gồm gì?" in p.rendered_text
    assert "Bạn cần CCCD." in p.rendered_text


def test_project_job_requirement_renders_text():
    row = SimpleNamespace(
        id=4,
        requirement_text="Nam 18-35 tuổi",
        category="age",
        is_required=True,
    )
    p = project_job_requirement(row)
    assert p.rendered_text == "Nam 18-35 tuổi"


def test_project_row_infers_entity_type_from_table_name():
    """A row without entity_type infers from __tablename__."""
    class FakeBenefit:
        __tablename__ = "job_benefit"
        id = 1
        name = "Test"
        scope_type = "global"
        value = None
        currency = None
        cadence = None
        eligibility = None

    p = project_row(FakeBenefit())
    assert p is not None
    assert p.entity_type == "benefit"


def test_project_row_returns_none_for_unrecognized():
    row = SimpleNamespace(id=99, name="unknown")
    assert project_row(row) is None


def test_projections_for_batch_skips_unrecognized():
    rows = [
        SimpleNamespace(id=1, name="B", scope_type="g", value=None, currency=None, cadence=None, eligibility=None, entity_type="benefit"),
        SimpleNamespace(id=2, name="unknown"),  # no entity_type, no tablename
    ]
    projections = projections_for_batch(rows)
    assert len(projections) == 1
    assert projections[0].entity_type == "benefit"


# ─── Review outcome classifier ───────────────────────────────────────────────


def test_review_outcomes_constants():
    assert "AUTO_PUBLISH" in REVIEW_OUTCOMES
    assert "HUMAN_REVIEW" in REVIEW_OUTCOMES
    assert "QUARANTINE" in REVIEW_OUTCOMES


def test_classify_outcome_auto_publish_when_clean():
    assert classify_outcome(issues=[], has_critical_field=False) == "AUTO_PUBLISH"


def test_classify_outcome_human_review_when_critical_field():
    assert classify_outcome(issues=[], has_critical_field=True) == "HUMAN_REVIEW"


def test_classify_outcome_human_review_when_errors():
    issues = [ValidationIssue("error", "bad", "really bad")]
    assert classify_outcome(issues=issues, has_critical_field=False) == "HUMAN_REVIEW"


def test_critical_fields_includes_benefit_value_and_bus_times():
    """Directive §9: bus times, salary, benefits, eligibility are critical."""
    assert "data.value" in CRITICAL_FIELDS
    assert "data.trips" in CRITICAL_FIELDS
    assert "data.start_time" in CRITICAL_FIELDS
