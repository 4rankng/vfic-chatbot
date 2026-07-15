"""Generic case, tag, note, and follow-up models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CaseLifecycle(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FollowupStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("id", "workflow_version_id", name="uq_case_workflow"),
        CheckConstraint("lifecycle IN ('OPEN','CLOSED','CANCELLED')", name="case_lifecycle_closed"),
        CheckConstraint("version > 0", name="case_version_positive"),
        CheckConstraint("jsonb_typeof(attributes) = 'object'", name="case_attributes_object"),
        CheckConstraint(
            "(lifecycle = 'OPEN') = (closed_at IS NULL)", name="case_lifecycle_closed_at"
        ),
        ForeignKeyConstraint(
            ["workflow_version_id", "workflow_checksum"],
            ["case_workflow_versions.id", "case_workflow_versions.checksum"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_version_id", "stage_key"],
            ["case_workflow_stages.workflow_version_id", "case_workflow_stages.stage_key"],
            ondelete="RESTRICT",
        ),
        Index("ix_cases_contact_updated", "contact_id", text("updated_at DESC")),
        Index(
            "ix_cases_assignee_lifecycle_updated",
            "assigned_user_id",
            "lifecycle",
            text("updated_at DESC"),
        ),
        Index(
            "ix_cases_workflow_stage_updated",
            "workflow_version_id",
            "stage_key",
            text("updated_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    case_no: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workflow_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CaseLifecycle.OPEN.value,
        server_default=CaseLifecycle.OPEN.value,
    )
    subject: Mapped[str | None] = mapped_column(String(240))
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CaseTagAssignment(Base):
    __tablename__ = "case_tag_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "workflow_version_id"],
            ["cases.id", "cases.workflow_version_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workflow_version_id", "tag_key"],
            ["case_tag_definitions.workflow_version_id", "case_tag_definitions.tag_key"],
            ondelete="RESTRICT",
        ),
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tag_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CaseNote(Base):
    __tablename__ = "case_notes"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CaseFollowup(Base):
    __tablename__ = "case_followups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','COMPLETED','CANCELLED')", name="case_followup_status_closed"
        ),
        CheckConstraint(
            "(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="case_followup_completed_at"
        ),
        CheckConstraint("version > 0", name="case_followup_version_positive"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=FollowupStatus.PENDING.value,
        server_default=FollowupStatus.PENDING.value,
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
