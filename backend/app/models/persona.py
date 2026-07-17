"""Persona ORM model — configurable agent personas (free-form markdown).

A persona is the bot's "voice". Several may be stored (``multiple personas for
different scenarios``); exactly one *global* persona (``project_id IS NULL``) is
``is_active`` at a time (enforced app-side by the activate endpoint + a DB partial
unique index). ``body_md`` is free-form markdown seeded from the 7-section
``persona.md`` template. ``project_id`` is reserved for a future per-project persona
override and is NULL for all global personas today.
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
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
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
