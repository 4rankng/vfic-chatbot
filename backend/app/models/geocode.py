"""Durable location→coordinates mapping for the geocoder."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GeocodeCache(Base):
    """One resolved geocoder query: the normalized text → coordinates, or a miss.

    The durable half of the geocoder cache (Redis holds the fast, expiring
    copy): a row with coordinates answers the same normalized query without any
    provider call; a row with NULL coordinates is a recorded miss. Misses expire
    by ``updated_at`` (the lookup treats an old miss as absent, so improving
    provider coverage is picked up); positives persist.
    """

    __tablename__ = "geocode_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    query: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # Which provider resolved the coordinates: "google" (primary hop) or
    # "vietmap" (secondary hop). NULL on a miss row. Free text — the geocoder
    # chain is free to gain a hop.
    provider: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
