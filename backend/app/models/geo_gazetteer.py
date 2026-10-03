"""Human-verified places that outrank every geocoder.

The gazetteer behind :mod:`app.services.geo.gazetteer`. A row here is a claim a
person made about a real place, so it is served without further verification —
which is exactly why it records where the claim came from.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GeoGazetteer(Base):
    """One verified place: its names, where it is, and who says so.

    ``name`` is the canonical label; ``aliases`` is a comma-separated list of
    the other names the same place is written under, and either form selects the
    row. ``source`` records provenance ("osm", "google", "recruiter") and
    ``verified_by`` who confirmed it — a row is served until someone edits it,
    so being able to say why it is trusted is part of the data, not a nicety.

    There is no proxy or cascade here on purpose: nothing geocoded is
    necessarily a gazetteer place, and deleting a verified location by deleting
    a project would quietly un-verify it.
    """

    __tablename__ = "geo_gazetteer"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    province: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    ward: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_by: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
