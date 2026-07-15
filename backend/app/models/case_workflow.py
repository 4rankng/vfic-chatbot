"""Immutable, administrator-authored case workflow definitions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CaseWorkflowVersion(Base):
    __tablename__ = "case_workflow_versions"
    __table_args__ = (
        UniqueConstraint("pack_key", "workflow_key", "version_no", name="uq_case_workflow_version"),
        UniqueConstraint("pack_key", "workflow_key", "checksum", name="uq_case_workflow_checksum"),
        UniqueConstraint("id", "checksum", name="uq_case_workflow_id_checksum"),
        CheckConstraint("version_no > 0", name="case_workflow_version_positive"),
        CheckConstraint("schema_version = 1", name="case_workflow_schema_v1"),
        CheckConstraint(
            "jsonb_typeof(case_attribute_schema) = 'object'", name="case_workflow_attributes_object"
        ),
        CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="case_workflow_checksum_sha256"),
        Index(
            "ix_case_workflow_versions_lookup", "pack_key", "workflow_key", text("version_no DESC")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    pack_key: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    case_attribute_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CaseWorkflowStage(Base):
    __tablename__ = "case_workflow_stages"
    __table_args__ = (
        UniqueConstraint("workflow_version_id", "position", name="uq_case_workflow_stage_position"),
        CheckConstraint("position >= 0", name="case_workflow_stage_position_nonnegative"),
        Index(
            "uq_case_workflow_one_initial",
            "workflow_version_id",
            unique=True,
            postgresql_where=text("is_initial"),
        ),
    )

    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("case_workflow_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stage_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_initial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CaseWorkflowTransition(Base):
    __tablename__ = "case_workflow_transitions"
    __table_args__ = (
        CheckConstraint("from_stage_key <> to_stage_key", name="case_workflow_transition_not_self"),
        ForeignKeyConstraint(
            ["workflow_version_id", "from_stage_key"],
            ["case_workflow_stages.workflow_version_id", "case_workflow_stages.stage_key"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workflow_version_id", "to_stage_key"],
            ["case_workflow_stages.workflow_version_id", "case_workflow_stages.stage_key"],
            ondelete="CASCADE",
        ),
    )

    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    from_stage_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    to_stage_key: Mapped[str] = mapped_column(String(64), primary_key=True)


class CaseTagDefinition(Base):
    __tablename__ = "case_tag_definitions"
    __table_args__ = (
        UniqueConstraint("workflow_version_id", "position", name="uq_case_tag_position"),
        CheckConstraint(
            "tone IN ('neutral','info','success','warning','danger')", name="case_tag_tone_closed"
        ),
        CheckConstraint("position >= 0", name="case_tag_position_nonnegative"),
    )

    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("case_workflow_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    tone: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
