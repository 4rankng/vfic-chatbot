"""Lead / lead_event / follow_up_task ORM models (mirror Alembic baseline)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LeadScore(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    not_interested = "not_interested"


class LeadStage(str, enum.Enum):
    NEW = "NEW"
    ENGAGED = "ENGAGED"
    QUALIFIED = "QUALIFIED"
    APPLIED = "APPLIED"
    HIRED = "HIRED"
    LOST = "LOST"
    UNQUALIFIED = "UNQUALIFIED"


class FollowupStatus(str, enum.Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    zalo_id: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    age: Mapped[int | None] = mapped_column(Integer)
    living_area: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    desired_job: Mapped[str | None] = mapped_column(Text)
    years_experience: Mapped[str | None] = mapped_column(Text)
    latest_company: Mapped[str | None] = mapped_column(Text)
    expected_salary: Mapped[str | None] = mapped_column(Text)
    lead_score: Mapped[LeadScore | None] = mapped_column(Enum(LeadScore, name="lead_score", create_type=False))
    lead_stage: Mapped[LeadStage] = mapped_column(
        Enum(LeadStage, name="lead_stage", create_type=False), nullable=False, default=LeadStage.NEW, server_default="NEW"
    )
    intent_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    qualification_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default=text("'{}'"))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_recruiter_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class LeadEvent(Base):
    __tablename__ = "lead_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    lead_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    lead_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[FollowupStatus] = mapped_column(
        Enum(FollowupStatus, name="followup_status", create_type=False), nullable=False, default=FollowupStatus.PENDING, server_default="PENDING"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
