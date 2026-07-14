"""Tests for the provenance + domain models (Tech-Lead Directive §7).

Schema-level smoke tests: each model class instantiates with valid field values,
and the enum values match the migration CHECK constraints. Full DB round-trip
requires `alembic upgrade head` (manual); these tests verify the ORM mapping
without needing a live Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date, time


from app.models import (
    DocumentStatus,
    ExtractionRun,
    ExtractionRunStatus,
    FaqEntry,
    FaqResolutionType,
    FieldEvidence,
    JobBenefit,
    JobLocation,
    JobRequirement,
    JobShift,
    KnowledgeScope,
    PublishedStatus,
    SourceDocument,
    SourceFragment,
    WorkingHours,
    WorkingHoursException,
)


# ─── Enum values ─────────────────────────────────────────────────────────────


def test_document_status_values_match_migration_check_constraint():
    expected = {
        "RECEIVED", "STORED", "PARSED", "NORMALIZED", "CLASSIFIED", "EXTRACTED",
        "VALIDATED", "REVIEW_REQUIRED", "APPROVED", "PUBLISHED", "INDEXED",
        "FAILED_TRANSIENT", "FAILED_PERMANENT", "QUARANTINED", "SUPERSEDED",
    }
    assert {s.value for s in DocumentStatus} == expected


def test_extraction_run_status_values_match_check_constraint():
    assert {s.value for s in ExtractionRunStatus} == {
        "PENDING", "RUNNING", "COMPLETED", "FAILED", "REVIEW_REQUIRED"
    }


def test_knowledge_scope_values_match_directive():
    """Directive §7: global/company/location/job_posting/campaign."""
    assert {s.value for s in KnowledgeScope} == {
        "global", "company", "location", "job_posting", "campaign"
    }


def test_published_status_values():
    assert {s.value for s in PublishedStatus} == {"draft", "published", "retired"}


def test_faq_resolution_type_values():
    assert {s.value for s in FaqResolutionType} == {"static_answer", "tool"}


# ─── Model instantiation (no DB; verifies column mapping) ────────────────────


def test_source_document_instantiates_with_required_fields():
    doc = SourceDocument(
        filename="bus_schedule.pdf",
        mime_type="application/pdf",
        storage_uri="s3://kb/bus_schedule.pdf",
        sha256="abc123",
        status="RECEIVED",
    )
    assert doc.filename == "bus_schedule.pdf"
    assert doc.status == "RECEIVED"


def test_source_fragment_instantiates_with_required_fields():
    frag = SourceFragment(
        document_id=1,
        block_type="table",
        block_order=0,
        original_text="B03 Biên Hòa → Factory A 06:10 06:40",
        section_type="bus_timetable",
    )
    assert frag.block_type == "table"
    assert frag.section_type == "bus_timetable"


def test_extraction_run_instantiates():
    run = ExtractionRun(source_document_id=1, status="PENDING")
    assert run.status == "PENDING"


def test_field_evidence_instantiates_with_provenance_fields():
    ev = FieldEvidence(
        extraction_run_id=1,
        source_fragment_id=1,
        field_path="data.trips[0].stops[0].departure_time",
        value="06:10",
        page_number=3,
        table_row=4,
        table_column=2,
        extraction_method="table_parser",
        confidence=0.99,
    )
    assert ev.extraction_method == "table_parser"
    assert ev.confidence == 0.99


def test_faq_entry_instantiates_with_scope_and_resolution():
    faq = FaqEntry(
        scope_type="global",
        canonical_question="Tôi cần chuẩn bị hồ sơ gì?",
        normalized_question="toi can chuan bi ho so gi",
        answer="Bạn cần CCCD, sơ yếu lý lịch...",
        language="vi",
        resolution_type="static_answer",
        status="published",
    )
    assert faq.resolution_type == "static_answer"
    assert faq.scope_type == "global"


def test_faq_entry_tool_resolution_carries_tool_name():
    faq = FaqEntry(
        scope_type="global",
        canonical_question="Giờ xe tiếp theo là?",
        normalized_question="gio xe tiep theo la",
        answer="",  # populated dynamically by the tool
        resolution_type="tool",
        tool_name="get_next_bus",
    )
    assert faq.tool_name == "get_next_bus"


def test_job_requirement_instantiates():
    req = JobRequirement(
        job_id=uuid.uuid4(),
        requirement_text="Nam, 18-35 tuổi",
        category="age",
        is_required=True,
        min_value="18",
        max_value="35",
        unit="years",
    )
    assert req.category == "age"
    assert req.is_required is True


def test_job_benefit_instantiates_with_money_fields():
    b = JobBenefit(
        job_id=uuid.uuid4(),
        scope_type="job_posting",
        name="Phụ cấp chuyên cần",
        category="ALLOWANCE",
        value=500000,
        currency="VND",
        cadence="monthly",
        eligibility="Đủ ngày công",
    )
    assert b.value == 500000
    assert b.currency == "VND"
    assert b.cadence == "monthly"


def test_job_shift_instantiates_with_midnight_flag():
    s = JobShift(
        job_id=uuid.uuid4(),
        schedule_type="SHIFT",
        days=["MON", "TUE", "WED"],
        start_time=time(22, 0),
        end_time=time(6, 0),
        crosses_midnight=True,
    )
    assert s.crosses_midnight is True


def test_job_location_instantiates():
    loc = JobLocation(
        job_id=uuid.uuid4(),
        address="KCN Amata, Biên Hòa",
        locality="Biên Hòa",
        region="Đồng Nai",
        is_primary=True,
    )
    assert loc.is_primary is True


def test_working_hours_instantiates_with_timezone():
    wh = WorkingHours(
        scope_type="company",
        schedule_type="FIXED",
        days=["MON", "TUE", "WED", "THU", "FRI", "SAT"],
        start_time=time(8, 0),
        end_time=time(17, 0),
        timezone="Asia/Ho_Chi_Minh",
    )
    assert wh.timezone == "Asia/Ho_Chi_Minh"


def test_working_hours_exception_instantiates():
    exc = WorkingHoursException(
        working_hours_id=1,
        exception_date=date(2026, 9, 2),  # Independence Day
        is_open=False,
        reason="Quốc khánh",
    )
    assert exc.is_open is False
    assert exc.reason == "Quốc khánh"


# ─── Validity windows (directive §7) ─────────────────────────────────────────


def test_every_time_sensitive_table_has_validity_windows():
    """Directive §7: 'Every time-sensitive record should support valid_from,
    valid_to, status, version.'"""
    from app.models import (
        FaqEntry,
        JobBenefit,
        JobRequirement,
        WorkingHours,
    )

    for model in (FaqEntry, JobBenefit, JobRequirement, WorkingHours):
        cols = {c.name for c in model.__table__.columns}
        assert "valid_from" in cols, f"{model.__name__} missing valid_from"
        assert "valid_to" in cols, f"{model.__name__} missing valid_to"
        assert "status" in cols, f"{model.__name__} missing status"
        assert "version" in cols, f"{model.__name__} missing version"


def test_every_scoped_table_has_scope_type_and_scope_id():
    """Directive §7: every domain table has scope_type + scope_id."""
    for model in (FaqEntry, JobBenefit, WorkingHours):
        cols = {c.name for c in model.__table__.columns}
        assert "scope_type" in cols, f"{model.__name__} missing scope_type"
        assert "scope_id" in cols, f"{model.__name__} missing scope_id"
