"""Human-verified places, consulted before any geocoder.

Every provider studied on 2026-10-03 failed to place at least one site this
bot serves: KCN Nomura is in no provider's index at all, and KCN VSIP comes
back with two readings ~4 km apart depending on whether the company name is in
the query. A recruiter knows where their own plant is; this table is where that
knowledge is recorded once.

A hit here is authoritative and FINAL: :mod:`app.services.geo.factory_point`
returns these coordinates directly, skipping the keyed geocoding hops AND the
reverse-verification lookup — the row IS the verification, because a person
asserted it. That makes resolution free and deterministic for every site that
has an entry, which is the only way to stop paying for (and re-litigating) an
answer a human could have supplied.

The trade is explicit and is why the table records provenance: a wrong row is
served until someone edits it. ``source`` says where the coordinate came from
and ``verified_by`` who confirmed it, so a bad row is traceable rather than
mysterious.

Matching is token-subset, never fuzzy. An entry (or one of its aliases) matches
an address component when every normalized word of the entry appears in that
component's words. "KCN Tràng Duệ" therefore matches
"Công ty 4P, KCN Tràng Duệ, An Phong, An Dương" and cannot match "An Dương" —
the discrimination that stops a gazetteer from answering a different question
than the one asked. The most specific component of the address wins, so an
address naming both a park and a ward prefers the park.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from app.core.db import async_session
from app.models.geo_gazetteer import GeoGazetteer
from app.services.geo.verification import geographic_tail, place_tokens

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GazetteerHit:
    """A verified place, and the name in the address that selected it."""

    point: tuple[float, float]
    name: str
    source: str


def _entry_words(value: str) -> frozenset[str]:
    return frozenset(place_tokens(value))


def _entry_names(entry: GeoGazetteer) -> tuple[str, ...]:
    names = [entry.name]
    names.extend(alias.strip() for alias in (entry.aliases or "").split(","))
    return tuple(name for name in names if name)


async def lookup(address: str) -> GazetteerHit | None:
    """The verified place this address names, or ``None``.

    Components are scanned most-specific first (the address itself, then its
    geographic tail) so an entry naming the whole park beats an entry naming a
    ward inside it. Never raises: a database problem is a miss, and the caller
    falls through to the geocoding chain.
    """
    text = (address or "").strip()
    if not text:
        return None
    tail = geographic_tail(text)
    components: list[str] = []
    for source_text in (text, tail) if tail != text else (text,):
        components.extend(
            part.strip() for part in source_text.split(",") if part.strip()
        )
    if not components:
        return None
    component_words = [_entry_words(component) for component in components]
    try:
        async with async_session() as db:
            rows = (await db.execute(select(GeoGazetteer).order_by(GeoGazetteer.name))).scalars().all()
    except Exception:  # noqa: BLE001 — the gazetteer is decoration, never a failure
        logger.warning("geo gazetteer lookup failed", exc_info=True)
        return None
    if not rows:
        return None
    for row in rows:
        for entry_name in _entry_names(row):
            words = _entry_words(entry_name)
            if not words:
                continue
            for index, available in enumerate(component_words):
                if words <= available:
                    return GazetteerHit(
                        point=(float(row.latitude), float(row.longitude)),
                        name=entry_name,
                        source=row.source,
                    )
    return None
