"""Durable origin→destination road-distance estimates for the catalog tools."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DistanceEstimate(Base):
    """One road estimate for a geocoded origin → destination point pair.

    Keys are the coordinate pair rounded to 5 decimal places (≈ 1.1 m): the
    origin always arrives geocoded, so the same stated address maps to the
    same row. ``duration_s`` is nullable — distance is the contract, travel
    time a bonus the providers usually return alongside. Failures are never
    stored; only successful estimates produce a row.
    """

    __tablename__ = "distance_estimate"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    origin_key: Mapped[str] = mapped_column(Text, nullable=False)
    destination_key: Mapped[str] = mapped_column(Text, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
