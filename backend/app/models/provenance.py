"""Provenance + authoritative domain models (Tech-Lead Directive §7).

The provenance spine (source_document, source_fragment, extraction_run,
field_evidence) backs every extracted authoritative record. Domain tables
(faq_entry, job_benefit, job_requirement, job_shift, job_location,
working_hours, working_hours_exception) hold the structured facts; their
material fields carry provenance via field_evidence.

Bus tables (bus_routes, bus_stops, bus_route_service_days) already exist from
baseline migration 0001 — their ORM models live in bus.py.

Runtime status: these tables are NOT the live serving path. The writers
(ingestion template pipeline, publishing publisher, recruitment adapter) and
the readers (knowledge tools domain_tools) were removed in Sept 2026 after an
audit showed none was reachable from production — no API router or worker ever
called them. The canonical FAQ the bot actually serves is chunk-based:
ProjectFaqService → KnowledgeChunk rows (category='faq') via
services/retrieval. The classes stay because models mirror the hand-written
Alembic schema (the physical tables still exist); a future migration may drop
them. Do NOT add new readers of these tables without wiring a production
entry point in the same change.

Scope/precedence (directive §7): every domain table has scope_type
(global/company/location/job_posting/campaign) + scope_id; resolution precedence
(job > location > company > global) lives in the tool layer (P1-3).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time as dt_time

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ─── Enums ───────────────────────────────────────────────────────────────────


class DocumentStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    STORED = "STORED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    CLASSIFIED = "CLASSIFIED"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    INDEXED = "INDEXED"
    FAILED_TRANSIENT = "FAILED_TRANSIENT"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"


class ExtractionRunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class KnowledgeScope(str, enum.Enum):
    """Directive §7 scope/precedence axis."""

    GLOBAL = "global"
    COMPANY = "company"
    LOCATION = "location"
    JOB_POSTING = "job_posting"
    CAMPAIGN = "campaign"


class PublishedStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class FaqResolutionType(str, enum.Enum):
    STATIC_ANSWER = "static_answer"
    TOOL = "tool"


# ─── Provenance spine ────────────────────────────────────────────────────────


class SourceDocument(Base):
    __tablename__ = "source_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RECEIVED")
    parser_version: Mapped[str | None] = mapped_column(String(32))
    extractor_version: Mapped[str | None] = mapped_column(String(32))
    schema_version: Mapped[str | None] = mapped_column(String(16))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceFragment(Base):
    __tablename__ = "source_fragment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_document.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(512))
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    block_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_type: Mapped[str | None] = mapped_column(String(32))
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    table_json: Mapped[dict | None] = mapped_column(JSONB)
    bounding_box: Mapped[dict | None] = mapped_column(JSONB)
    fragment_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExtractionRun(Base):
    __tablename__ = "extraction_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_document.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extractor_version: Mapped[str | None] = mapped_column(String(32))
    schema_version: Mapped[str | None] = mapped_column(String(16))
    stats: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FieldEvidence(Base):
    __tablename__ = "field_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("extraction_run.id", ondelete="CASCADE"), nullable=False
    )
    source_fragment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_fragment.id", ondelete="SET NULL")
    )
    field_path: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    table_row: Mapped[int | None] = mapped_column(Integer)
    table_column: Mapped[int | None] = mapped_column(Integer)
    char_range: Mapped[str | None] = mapped_column(String(32))
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ─── FAQ ─────────────────────────────────────────────────────────────────────


class FaqEntry(Base):
    """Canonical FAQ table (directive §7). The existing ``faq_bypass_rule_terms``
    (migration 0026) is a different thing — matching terms — and stays."""

    __tablename__ = "faq_entry"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "normalized_question",
            name="uq_faq_entry_scope_normalized_question",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    scope_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="UUID of the scope entity (project/job/company)"
    )
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE")
    )
    canonical_question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSONB)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi")
    resolution_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FaqResolutionType.STATIC_ANSWER.value
    )
    tool_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="For dynamic FAQs: the tool to invoke"
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ─── Job domain (child tables of jobs) ───────────────────────────────────────


class JobRequirement(Base):
    __tablename__ = "job_requirement"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE")
    )
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(
        String(32), comment="age|experience|education|gender|skill|document|other"
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    min_value: Mapped[str | None] = mapped_column(String(64))
    max_value: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str | None] = mapped_column(String(32))
    evidence_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("field_evidence.id", ondelete="SET NULL")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobBenefit(Base):
    __tablename__ = "job_benefit"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "scope_type",
            "name",
            "status",
            name="uq_job_benefit_scope_name_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
        comment="NULL when scope_type != job_posting",
    )
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE")
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="job_posting")
    scope_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(
        String(32), comment="ALLOWANCE|INSURANCE|ACCOMMODATION|TRANSPORT|MEAL|BONUS|OTHER"
    )
    value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(8), comment="ISO 4217 e.g. VND")
    cadence: Mapped[str | None] = mapped_column(
        String(16), comment="hourly|daily|monthly|annual|one_time"
    )
    eligibility: Mapped[str | None] = mapped_column(Text)
    taxable: Mapped[bool | None] = mapped_column(Boolean)
    evidence_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("field_evidence.id", ondelete="SET NULL")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobShift(Base):
    __tablename__ = "job_shift"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE")
    )
    schedule_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="FIXED", comment="FIXED|ROTATING|SHIFT"
    )
    days: Mapped[list | None] = mapped_column(JSONB, comment="['MON','TUE',...]")
    start_time: Mapped[dt_time | None] = mapped_column()
    end_time: Mapped[dt_time | None] = mapped_column()
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, default=False)
    breaks: Mapped[list | None] = mapped_column(JSONB)
    exceptions: Mapped[list | None] = mapped_column(JSONB)
    evidence_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("field_evidence.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobLocation(Base):
    __tablename__ = "job_location"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE")
    )
    address: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(String(128), comment="City/district")
    region: Mapped[str | None] = mapped_column(String(128), comment="Province")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("field_evidence.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ─── Working hours ───────────────────────────────────────────────────────────


class WorkingHours(Base):
    __tablename__ = "working_hours"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    scope_id: Mapped[str | None] = mapped_column(String(64))
    kb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE")
    )
    schedule_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="FIXED", comment="FIXED|ROTATING|SHIFT"
    )
    days: Mapped[list | None] = mapped_column(JSONB)
    start_time: Mapped[dt_time | None] = mapped_column()
    end_time: Mapped[dt_time | None] = mapped_column()
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, default=False)
    breaks: Mapped[list | None] = mapped_column(JSONB)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Ho_Chi_Minh")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("field_evidence.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkingHoursException(Base):
    __tablename__ = "working_hours_exception"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    working_hours_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("working_hours.id", ondelete="CASCADE"), nullable=False
    )
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    open_time: Mapped[dt_time | None] = mapped_column()
    close_time: Mapped[dt_time | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(String(128), comment="Holiday name etc.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Avoid a circular re-export; the bus ORM models go in bus.py.
