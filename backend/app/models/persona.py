"""Persona ORM model — configurable agent personas (free-form markdown).

A persona is the bot's voice and proactive follow-up policy. Several may be
stored, but exactly one row is the active global default (enforced app-side by
the activate endpoint + a DB partial unique index). Adapter-specific overrides
live in ``adapter_persona_assignments`` keyed by canonical provider id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def default_persona_followup_rules() -> dict:
    return {
        "hot": {
            "enabled": True,
            "cadence_hours": [10, 22, 46],
            "eligible_stages": ["NEW"],
        },
        "warm": {
            "enabled": True,
            "cadence_hours": [22, 46],
            "eligible_stages": ["NEW"],
        },
        "not_interested": {
            "enabled": True,
            "cadence_hours": [46],
            "eligible_stages": ["NEW"],
        },
    }


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    followup_rules: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=default_persona_followup_rules
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AdapterPersonaAssignment(Base):
    __tablename__ = "adapter_persona_assignments"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('zalo_bot', 'zalo_oa', 'facebook_messenger')",
            name="adapter_persona_assignments_provider_valid",
        ),
    )

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PersonaVersion(Base):
    """Immutable persona content pinned by installation revisions."""

    __tablename__ = "persona_versions"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="persona_versions_positive_version"),
        CheckConstraint(
            "jsonb_typeof(followup_rules) = 'object'",
            name="persona_versions_followup_rules_object",
        ),
        CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="persona_versions_checksum_sha256"),
        UniqueConstraint("persona_id", "version_no", name="persona_versions_identity_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personas.id", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    followup_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
