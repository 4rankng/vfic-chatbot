"""Durable reverse-geocoded place names per coordinate.

The verification half of the geocoder: :class:`~app.models.geocode.GeocodeCache`
remembers "this text is at these coordinates", and this remembers "these
coordinates are in a place called X, Y, Z". The second is what lets a project
coordinate be checked against the ward its own address names — see
``app.services.geo.verification``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GeocodePlaceCheck(Base):
    """One coordinate → the place names a reverse lookup reported for it.

    Only successful lookups are stored, so a row's existence means "this point
    has been looked up once and will never be looked up again". ``place_names``
    holds the normalized place names, **one per line** — the line boundary is
    load-bearing, because a containment check asks whether an anchor's words all
    appear inside ONE reported name. Joining with spaces instead would collapse
    the names into a bag of single words, after which no multi-word anchor
    ("an phong", "trang due") could ever match again and every project would go
    silent on the next resolution. An empty string is a real answer ("nothing
    here in particular"). A point that could not be looked up has NO row and is
    retried on the next pass.
    """

    __tablename__ = "geocode_place_check"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    coord_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    place_names: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
