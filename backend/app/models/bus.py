"""Structured Project bus timetable projections."""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, String, Text, Time, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BusRoute(Base):
    __tablename__ = "bus_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_category_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_category_revisions.id", ondelete="CASCADE"),
    )
    route_name: Mapped[str] = mapped_column(Text, nullable=False)
    route_no: Mapped[str | None] = mapped_column(Text)
    route_variant: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shift: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    area: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    route_group_key: Mapped[str] = mapped_column(Text, nullable=False)


class BusStop(Base):
    __tablename__ = "bus_stops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bus_routes.id", ondelete="CASCADE"), nullable=False
    )
    stop_order: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_name: Mapped[str] = mapped_column(Text, nullable=False)
    stop_aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    scheduled_time: Mapped[time | None] = mapped_column(Time)
    raw_stop_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
