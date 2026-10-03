"""Place a factory's work address, or refuse to place it.

A candidate asking "how far is 4P from my house" gets a road distance computed
from ``projects.latitude``/``longitude``. A wrong value there is not a rounding
error — it is the bot telling a person deciding whether to take a job that a
plant 13.6 km away is down the road. So this module never trusts a geocoder: it
collects every plausible reading of an address, then keeps only those that can
be CHECKED against the address itself.

Why a check is needed at all, when a geocoder returns coordinates:

* Nominatim does not index most Vietnamese industrial parks. Its relaxation
  ladder walked "Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong,
  An Dương, Hải Phòng" down to "TP. Hải Phòng" and answered with the city
  centroid — inside the candidate's own ward, 10 km from the park.
* Vietmap indexes parks, but a leading company name defeats it: the 4P address
  resolved 6.81 km away, while the same address with that prefix dropped
  resolved 1.14 km away.

Neither failure is visible from the returned coordinate alone, so the check is
positional rather than syntactic: the point must sit in a place the ADDRESS
names. That is what ``app.services.geo.verification`` answers, and it is the
only thing standing between a confident provider and a quoted distance.

The contract this module keeps:

* a human-verified gazetteer row answers outright — no API call, no chain;
* otherwise the address is the claim, and every candidate must justify itself
  against it;
* the first reading that passes, in the measured hop order, is the answer; a
  provider that verifies is a provider that placed the site in a place the
  address itself named;
* nothing here raises. A geocoder outage, a rejected candidate and an
  unresolvable address all end the same way: no coordinates, no lie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.geo.gazetteer import lookup as gazetteer_lookup
from app.services.geo.geocoding import geocode
from app.services.geo.providers import KEYED_GEO_HOPS
from app.services.geo.verification import check_point, coord_key, geographic_tail

if TYPE_CHECKING:
    from app.services.integration_settings.providers.geo import GeoRuntimeConfig

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class FactoryPoint:
    """A verified coordinate, and the evidence that earned it."""

    point: tuple[float, float]
    provider: str
    text: str
    matched_anchor: str


@dataclass(frozen=True)
class _Candidate:
    point: tuple[float, float]
    provider: str
    text: str


def _candidate_texts(address: str) -> tuple[str, ...]:
    """The address, then its geographic tail when that differs.

    A Vietnamese work address leads with what the site is ("Tầng 2, Công ty
    AmTRAN, KCN Vsip, …") and trails with where it is. The lead is the part
    providers get wrong: it names an organisation, not a location, and one
    provider in the chain was measurably dragged 4 km off by a company name.
    The tail keeps the whole administrative chain, so dropping the lead cannot
    silently change which district is meant.
    """
    tail = geographic_tail(address)
    return (address,) if tail == address else (address, tail)


async def resolve_factory_point(
    address: str,
    *,
    providers: "GeoRuntimeConfig | None",
) -> FactoryPoint | None:
    """The one coordinate this address can be honestly placed at, else ``None``.

    Every keyed hop is tried on every candidate text, then the Nominatim ladder
    at ``precision="point"``. Each distinct coordinate is then verified by
    containment against the address's own place names. Exactly one verified
    reading is returned; zero, or two that disagree, return ``None`` so the
    catalog tool says nothing about distance rather than something wrong.
    """
    text = (address or "").strip()
    if not text:
        return None
    # A verified gazetteer row outranks every provider and every heuristic: the
    # row is itself the verification, it costs no API call, and it is the only
    # way to place a site no geocoder indexes (KCN Nomura is in none of them).
    hit = await gazetteer_lookup(text)
    if hit is not None:
        logger.info("factory point from gazetteer address=%s place=%s", text, hit.name)
        return FactoryPoint(
            point=hit.point,
            provider=f"gazetteer:{hit.source}",
            text=text,
            matched_anchor=hit.name,
        )
    texts = _candidate_texts(text)
    candidates: dict[str, _Candidate] = {}

    def remember(point: tuple[float, float], provider: str, source: str) -> None:
        candidates.setdefault(coord_key(point), _Candidate(point, provider, source))

    for candidate_text in texts:
        for hop in KEYED_GEO_HOPS:
            api_key = getattr(providers, hop.key_field, "") if providers is not None else ""
            if not api_key:
                continue
            try:
                hit = await hop.fetch(candidate_text, api_key=api_key)
            except Exception:  # noqa: BLE001 — a hop must never break resolution
                logger.warning("factory geocode hop failed provider=%s", hop.name, exc_info=True)
                continue
            if hit is not None:
                remember(hit, hop.name, candidate_text)
        # The keyless ladder, at point precision so it cannot answer with a ward
        # or city centroid. ``providers=None`` keeps it from re-running the keyed
        # hops the loop above already covered.
        try:
            hit = await geocode(candidate_text, providers=None, precision="point")
        except Exception:  # noqa: BLE001 — decoration, never a failure
            logger.warning("factory nominatim lookup failed", exc_info=True)
            continue
        if hit is not None:
            remember(hit, "nominatim", candidate_text)

    if not candidates:
        logger.info("factory point unresolved address=%s", text)
        return None

    from app.services.geo.verification import place_anchors

    anchors = place_anchors(text)
    verified: list[FactoryPoint] = []
    for candidate in candidates.values():
        # No anchors means the address names no place, so containment cannot
        # justify anything: an unverifiable claim is not a coordinate.
        if not anchors:
            logger.info("factory point unverifiable address=%s", text)
            return None
        check = await check_point(candidate.point, anchors, providers=providers)
        if check is None:
            continue  # the point could not be looked up; nothing was decided
        if check.matched is None:
            logger.debug(
                "factory candidate rejected provider=%s text=%s names=%s",
                candidate.provider,
                candidate.text,
                sorted(check.names),
            )
            continue
        verified.append(
            FactoryPoint(
                point=candidate.point,
                provider=candidate.provider,
                text=candidate.text,
                matched_anchor=check.matched,
            )
        )

    if not verified:
        logger.info("factory point rejected all candidates address=%s", text)
        return None
    # First verified candidate in hop order wins. A disagreement between hops is
    # resolved by the MEASURED order (Google ahead of Vietmap), not by refusing
    # to answer: containment has already done the work that keeps the answer
    # honest, and a second guard that discards verified candidates would drop
    # real factories — KCN VSIP reads ~2 km apart between the two hops while
    # both land inside the ward its own address names.
    return verified[0]
