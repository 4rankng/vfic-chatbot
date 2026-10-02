"""Project + Company ORM models (bus-timetable knowledge graph parents; jobs FK target).

A ``Project`` doubles as a "product" in the agent's master index: ``is_active``
controls whether it appears in the catalog offered to candidates, and ``index_card``
holds the LLM-generated catalog entry (summary/roles/location/highlights).
Persona selection is provider-scoped and does not live on projects.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # "Product catalog" fields — populated/refreshed by the training pipeline.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    index_card: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    discovery_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    category_authority_started: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    category_cutover_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    # RETIRED COLUMN: the per-project integration that wrote it (and the
    # ``call_project_api`` tool that read it) was removed when the employee
    # password-reset flow moved to the deployment-wide TingTing integration
    # (ADR-0012). The nullable column stays because dropping it would be a
    # destructive migration; nothing reads or writes it.
    external_api: Mapped[dict | None] = mapped_column(JSONB)
    category_cutover_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_kb_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kb_versions.id", ondelete="SET NULL")
    )
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # Work-address geocoding ("dự án nào gần nhà"): the AI extracts the work
    # address from the uploaded brief (``extracted_address`` is that verbatim
    # value, grounded against the brief and reused as the re-ingest cache) and
    # the geocoder resolves it to ``latitude``/``longitude``. All three stay
    # NULL for a project whose brief states no work address or that cannot be
    # geocoded; the catalog tool then omits ``distance_km`` for it.
    # Not exposed through the projects API — no caller needs it.
    extracted_address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
