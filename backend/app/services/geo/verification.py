"""Can this coordinate be trusted to BE that address?

The 2026-10-03 incident, in one line: every geocoder available here will answer
a Vietnamese factory address with a confident coordinate, and none of them is
reliable enough on its own. Vietmap indexes parks, but a leading company name
defeats it: the exact 4P address resolved 6.8 km north-east of KCN Tràng Duệ,
while the same address with that prefix dropped resolved 1.1 km away. The
keyless provider that used to sit behind it did worse — its relaxation ladder
walked "Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong, An
Dương, Hải Phòng" all the way down to "TP. Hải Phòng" and answered with the city
centroid, 10 km from the park and inside the candidate's own ward — which is why
it was removed on 2026-10-03 rather than gated.

So a coordinate is accepted here only when it can be CHECKED against the address
that produced it. Two pieces do that work:

``geographic_tail``
    Strips the components of a work address that carry no location at all — a
    floor ("Tầng 2"), a company ("Công ty AmTRAN"), a building. Vietnamese
    addresses are written most-specific first, so these sit at the front. What
    remains is the address's own administrative chain, which is the part every
    provider is actually good at.

``place_matches``
    The containment test: does the point sit in a place the address NAMED?
    ``geocode_place_check`` caches the reverse-lookup answer per coordinate, so
    the check costs one HTTP call per distinct point, ever — not per address.

Neither is a heuristic dressed as a guarantee, and both are narrow on purpose:
a component is only a location if it is recognisably a place, and a point only
passes if it matches a name the address itself supplied. A factory that cannot
be placed under those rules gets no coordinates at all, and the catalog tool
then says nothing about distance. Silence is the correct failure here: a wrong
number is quoted back to a candidate deciding whether to take a job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import async_session
from app.models.geocode_place_check import GeocodePlaceCheck
from app.services.geo.providers import google_reverse
from app.shared.domain.text import normalize_vietnamese_text

if TYPE_CHECKING:
    from app.services.integration_settings.providers.geo import GeoRuntimeConfig

logger = logging.getLogger(__name__)

# 5 dp ≈ 1.1 m — the same rounding `distance_estimate` uses, for the same
# reason: a provider returning one facility twice is one row, not two.
_COORD_FORMAT = "{:.5f}"

# The rules version of the STORED answer, mirroring `geocoding._DB_KEY_VERSION`.
# `geocode_place_check` holds what the reverse sources reported for a point, so
# the row is only meaningful against the source set and parsing rules that
# produced it. Both changed on 2026-10-03: Nominatim was dropped (Google is now
# the only source) and Google's `formatted_address` is split per place instead
# of stored whole, which changes what a stored name means. Bumping the prefix
# retires the old rows with no migration: the column is opaque text.
_RULES_VERSION = "v7"

# Components that name an organisation or a building, not a place. Anything
# containing one of these is dropped from the front of the address, and is
# never used as an anchor.
_NON_PLACE_MARKERS = (
    "cong ty",
    "cty",
    "tap doan",
    "doanh nghiep",
    "chianh",
    "chi nhanh",
    "van phong",
    "nha may",
    "xi nghiep",
    "hop tac xa",
    "lien doanh",
    "tnhh",
    "co phan",
    "tu nhan",
    "tang",
    "lau",
    "toa nha",
    "to a nha",
    "can ho",
    "office",
    "floor",
)

# Facility-type words that carry no distinguishing information: "KCN Đình Vũ" and
# "Khu Công Nghiệp Đình Vũ" are the same place, but the second is how OpenStreetMap
# names it, so an anchor built from the first must not require the literal token
# "kcn". Stripping them from the front of an anchor leaves the words that
# actually identify the site.
_FACILITY_PREFIXES = (
    "khu cong nghiep",
    "khu che xuat",
    "khu vui choi",
    "khu du lich",
    "kcn",
    "kcc",
    "khu",
    "cct",
    "zone",
)

# A name longer than this is prose, not a place ("Quoc lo 10 di qua dia diem
# cong nghiep"), and matching it against a reverse response would match anything.
_MAX_ANCHOR_CHARS = 60


def coord_key(point: tuple[float, float]) -> str:
    """The durable cache key for a coordinate.

    Version-prefixed: the stored value is the union of the *current* reverse
    sources under the current parsing rules (see ``_RULES_VERSION``), so
    changing which sources feed it must retire the old answers rather than keep
    serving them under a new regime.
    """
    return (
        f"{_RULES_VERSION}:{_COORD_FORMAT.format(point[0])},"
        f"{_COORD_FORMAT.format(point[1])}"
    )


def place_tokens(value: str) -> tuple[str, ...]:
    """Normalized alphanumeric words of a component."""
    normalized = normalize_vietnamese_text(value)
    return tuple(
        word
        for word in "".join(
            ch if ch.isalnum() or ch.isspace() else " " for ch in normalized
        ).split()
        if len(word) > 1
    )


def _is_noise(component: str) -> bool:
    """Whether this component names an organisation or a building."""
    normalized = normalize_vietnamese_text(component)
    return any(marker in normalized for marker in _NON_PLACE_MARKERS)


def _strip_facility_prefix(words: tuple[str, ...]) -> tuple[str, ...]:
    """"kcn dinh vu" → "dinh vu"; leaves a bare "cct"/"khu" with nothing to say."""
    for prefix in _FACILITY_PREFIXES:
        prefix_words = tuple(prefix.split())
        if words[: len(prefix_words)] == prefix_words:
            return words[len(prefix_words) :] or words
    return words


def geographic_tail(address: str) -> str:
    """The address with its leading organisation/floor components removed.

    "Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong, An Dương,
    Hải Phòng" → "KCN Tràng Duệ, An Phong, An Dương, Hải Phòng".

    Returns the address unchanged when it has no removable prefix, so a plain
    "KCN Đình Vũ, Hải Phòng" is never altered. Only LEADING components are
    dropped: Vietnamese addresses are written most-specific first, so the
    organisation is at the front and the administrative chain behind it is
    exactly what must survive intact. Stopping at the first component that is
    NOT an organisation (rather than at the first one that looks like a place)
    is what keeps this safe — there is no lexical test here that a Vietnamese
    proper noun can accidentally trip.
    """
    parts = [part.strip() for part in address.split(",") if part.strip()]
    start = 0
    while start < len(parts) - 1 and _is_noise(parts[start]):
        start += 1
    tail = ", ".join(parts[start:])
    return tail or address


def place_anchors(address: str) -> tuple[str, ...]:
    """The names a resolved point must match for the address to be placed.

    Two deliberate exclusions, both of which would otherwise make the check
    meaningless:

    * **The coarsest component is dropped.** Vietnamese addresses end with the
      city, and every point in Hải Phòng reports "Thành phố Hải Phòng" — keep
      it and the check passes for the whole city, including the 10 km-off
      centroid that caused the incident.
    * **Organisation components are dropped.** They are not places, and nothing
      reverse-geocodes to "Công ty AmTRAN".

    What is left is the part that can distinguish one facility from another: the
    park, the ward, the road. A match on ANY of them is enough — the ward is
    there precisely for the large parks that span several.
    """
    parts = [part.strip() for part in address.split(",") if part.strip()]
    # The last component is the coarsest by address convention.
    candidates = parts[:-1] if len(parts) > 1 else []
    anchors: list[str] = []
    for part in candidates:
        if _is_noise(part) or len(part) > _MAX_ANCHOR_CHARS:
            continue
        words = _strip_facility_prefix(place_tokens(part))
        if not words:
            continue
        candidate = " ".join(words)
        if candidate not in anchors:
            anchors.append(candidate)
    return tuple(anchors)


def place_matches(names: frozenset[str], anchor: str) -> bool:
    """Whether a reverse-lookup name set contains ``anchor``.

    Containment is tested on whole words, not substrings: "an phong" must not
    match "phong an", and "xa" must not match "xay". An anchor matches when all
    of its words appear in one reported name, or when the anchor is a single
    word that appears as a whole word in one reported name.
    """
    anchor_words = anchor.split()
    if not anchor_words:
        return False
    for name in names:
        name_words = name.split()
        if all(word in name_words for word in anchor_words):
            return True
    return False


async def _cached_names(point: tuple[float, float]) -> frozenset[str] | None:
    """Stored place names for a point; ``None`` when never looked up."""
    try:
        async with async_session() as db:
            row = (
                await db.execute(
                    select(GeocodePlaceCheck.place_names).where(
                        GeocodePlaceCheck.coord_key == coord_key(point)
                    )
                )
            ).first()
    except Exception:  # noqa: BLE001 — the cache is decoration, never a failure
        logger.warning("place check db lookup failed", exc_info=True)
        return None
    if row is None:
        return None
    return frozenset(line for line in str(row[0]).split("\n") if line)


async def _store_names(point: tuple[float, float], names: frozenset[str]) -> None:
    """Record a successful lookup; never raises."""
    joined = "\n".join(sorted(names))
    try:
        async with async_session() as db:
            await db.execute(
                pg_insert(GeocodePlaceCheck)
                .values(coord_key=coord_key(point), place_names=joined)
                .on_conflict_do_update(
                    index_elements=[GeocodePlaceCheck.coord_key],
                    set_={"place_names": joined, "updated_at": datetime.now(UTC)},
                )
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — the cache is decoration, never a failure
        logger.warning("place check db store failed", exc_info=True)


@dataclass(frozen=True)
class PlaceCheck:
    """The verdict on one candidate coordinate."""

    point: tuple[float, float]
    matched: str | None
    names: frozenset[str]


async def _lookup_names(
    point: tuple[float, float], providers: "GeoRuntimeConfig | None"
) -> frozenset[str] | None:
    """The place names a keyed reverse service reports; ``None`` if none answered.

    Google only. Nominatim was dropped deliberately, for three reasons that all
    pointed the same way: it is the source of the 2026-10-03 incident (its
    relaxation ladder answered a KCN address with the Hải Phòng city centroid),
    its public instance rate-limits hard enough that verification returns
    nothing mid-run, and its OSM park polygons are already covered — every
    seeded gazetteer row and Google's own ``address_components`` name the same
    places. A verification step that can be throttled into silence is not a
    safety net.

    ``None`` means unverified rather than rejected, so the next pass retries.
    """
    google_key = getattr(providers, "google_maps_api_key", "") if providers else ""
    if not google_key:
        return None
    return await google_reverse(*point, api_key=google_key)


async def check_point(
    point: tuple[float, float],
    anchors: tuple[str, ...],
    *,
    providers: "GeoRuntimeConfig | None" = None,
) -> PlaceCheck | None:
    """Verify ``point`` against the place names ``address`` supplied.

    ``None`` when the point could not be looked up at all (a retryable miss),
    never for a point that was looked up and failed to match — that is a
    ``PlaceCheck`` with ``matched is None``, which callers treat as a rejection.
    An address with no anchors cannot be checked by containment, so it is left
    to the caller's own precision rules and returns ``None`` here.
    """
    if not anchors:
        return None
    names = await _cached_names(point)
    if names is None:
        names = await _lookup_names(point, providers)
        if names is None:
            return None
        await _store_names(point, names)
    for anchor in anchors:
        if place_matches(names, anchor):
            return PlaceCheck(point=point, matched=anchor, names=names)
    return PlaceCheck(point=point, matched=None, names=names)
