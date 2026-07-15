"""Versioned, declarative knowledge-ingestion templates and release-scoped facts."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TemplateVersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"


class IngestionRunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY = "READY"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    PREVIEW = "PREVIEW"


class IngestionTemplate(Base):
    __tablename__ = "ingestion_templates"
    __table_args__ = (UniqueConstraint("template_key", name="uq_ingestion_template_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    template_key: Mapped[str] = mapped_column(String(96), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    vertical: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionTemplateVersion(Base):
    __tablename__ = "ingestion_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_no", name="uq_ingestion_template_version_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_templates.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TemplateVersionStatus] = mapped_column(
        Enum(TemplateVersionStatus, name="ingestion_template_version_status", create_type=False),
        nullable=False,
        default=TemplateVersionStatus.DRAFT,
        server_default="DRAFT",
    )
    definition: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    compiled_artifact: Mapped[dict | None] = mapped_column(JSONB)
    checksum: Mapped[str | None] = mapped_column(String(64))
    compiler_version: Mapped[str | None] = mapped_column(String(32))
    preview_checksum: Mapped[str | None] = mapped_column(String(64))
    previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class IngestionTemplateAssignment(Base):
    __tablename__ = "ingestion_template_assignments"
    __table_args__ = (
        UniqueConstraint("project_id", "revision", name="uq_ingestion_assignment_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    replaces_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_template_assignments.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class KBIngestionRun(Base):
    __tablename__ = "kb_ingestion_runs"
    __table_args__ = (
        UniqueConstraint("kb_version_id", "attempt_no", name="uq_kb_ingestion_run_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kb_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE"), nullable=False
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[IngestionRunStatus] = mapped_column(
        Enum(IngestionRunStatus, name="kb_ingestion_run_status", create_type=False),
        nullable=False,
        default=IngestionRunStatus.PENDING,
        server_default="PENDING",
    )
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fencing_token: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issues: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    stats: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class KBIngestionFileRun(Base):
    __tablename__ = "kb_ingestion_file_runs"
    __table_args__ = (UniqueConstraint("run_id", "file_id", name="uq_kb_ingestion_file_run"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_text_files.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_document.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    issues: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class StructuredFact(Base):
    __tablename__ = "structured_facts"
    __table_args__ = (
        UniqueConstraint(
            "kb_version_id",
            "record_type_key",
            "natural_key_hash",
            name="uq_structured_fact_release_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kb_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="CASCADE"), nullable=False
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_ingestion_runs.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_text_files.id", ondelete="SET NULL")
    )
    record_type_key: Mapped[str] = mapped_column(String(96), nullable=False)
    source_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default="sourced_fact", server_default="sourced_fact"
    )
    natural_key: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    natural_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    scope_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="global", server_default="global"
    )
    scope_id: Mapped[str | None] = mapped_column(String(96))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
