"""Job ORM model (mirror Alembic baseline)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.recruitment.domain.statuses import JobStatus


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    factory_name: Mapped[str | None] = mapped_column(String)
    province: Mapped[str | None] = mapped_column(String)
    district: Mapped[str | None] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    shift: Mapped[str | None] = mapped_column(String)
    gender_requirement: Mapped[str | None] = mapped_column(String)
    age_min: Mapped[int | None] = mapped_column(Integer)
    age_max: Mapped[int | None] = mapped_column(Integer)
    experience_required: Mapped[str | None] = mapped_column(String)
    accommodation_support: Mapped[bool | None] = mapped_column(Boolean)
    meal_support: Mapped[bool | None] = mapped_column(Boolean)
    transport_support: Mapped[bool | None] = mapped_column(Boolean)
    vacancy_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", create_type=False),
        nullable=False,
        default=JobStatus.ACTIVE,
        server_default="ACTIVE",
    )
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    benefits: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="SET NULL")
    )
    stable_key: Mapped[str | None] = mapped_column(String(64))
    source_category_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_category_revisions.id", ondelete="CASCADE"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
