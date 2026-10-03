"""Keyed geocoding client for project work addresses and candidate areas.

Why this exists: candidates ask "dự án nào gần nhà tôi?" and nothing in the
system carried coordinates. The candidate's area already arrives every turn
(``leads.region``/``living_area``) and the project's work address is in the KB
brief, so one forward geocode per distinct string turns both into a distance.

Providers: the keyed hops in :data:`~app.services.geo.providers.KEYED_GEO_HOPS`
— **Google** first, **Vietmap** second, in that measured order. There is no
keyless provider: Nominatim was removed on 2026-10-03 because its relaxation
ladder answered a KCN Tràng Duệ address with the Hải Phòng city centroid (the
"1.5 km" incident), and because its public instance throttles at one request
per second, which turns a free fallback into a latency floor. A deployment with
no key therefore resolves nothing and the catalog tool omits ``distance_km``
instead of quoting a number nobody can stand at.

Each hop is called with the caller's EXACT text, once. Relaxation is not
offered to them: a keyed provider answers a partial query with a confident
wrong match rather than nothing ("tran phu" resolves to Phường Trần Phú, Hà
Tĩnh), so dropping components would trade a miss for a wrong answer. The
provider's own ranking does the work instead, and a region bias — the
candidate's viewbox, converted to Vietmap's ``focus`` — steers it.

Caching: two tiers keyed by the accent-insensitive normalized query.
``geo:geocode:v7:<sha256[:32]>`` holds either ``{"lat": …, "lng": …}`` for
``geocoder_cache_ttl_seconds`` (30 days) or ``{"miss": true}`` for
``geocoder_negative_ttl_seconds`` (6 hours). The negative tier is why a repeated
unresolvable area costs no network call. The key carries its version because
the chain that produced a stored value changed; a bump retires entries written
under the previous chain instead of serving them for their full TTL.

Precision: what an answer is allowed to be depends on WHO is being placed. A
candidate's own area only has to rank projects ("rough enough to sort"), so
``precision="area"`` — the default — accepts a ward or city answer. A project's
work address is quoted back to candidates as a road distance to a factory gate,
so it runs ``precision="point"``: the Google hop then refuses an answer whose
``types`` name a populated place or an administrative boundary (see
``providers._COARSE_PLACE_TYPES``), because a centroid is a miss wearing a
coordinate. A miss is strictly better — the caller reports "chưa xác định được"
instead of a confident wrong distance.

Fail-open by contract: an outage, timeout, non-200, or malformed payload
returns ``None`` and logs — never raises. Callers (project ingest, the catalog
tool) treat ``None`` as "no coordinates", which degrades to today's behavior.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.core.db import async_session
from app.models.geocode import GeocodeCache
from app.services.geo.providers import KEYED_GEO_HOPS
from app.shared.domain.text import normalize_vietnamese_text

if TYPE_CHECKING:
    from app.services.integration_settings.providers.geo import GeoRuntimeConfig

logger = logging.getLogger(__name__)

# v7: the chain became keyed-only. A coordinate is only as good as the chain
# that produced it, so a v6 entry — which could have been resolved by
# Nominatim's relaxation ladder, at ward or city precision — no longer means the
# same thing as one resolved by Google or Vietmap on the caller's exact text.
# v6 was the measured hop reorder (Google ahead of Vietmap); v5 was the
# ``precision="point"`` gate; v4 the Vietmap reorder.
_CACHE_PREFIX = "geo:geocode:v7:"
# The DURABLE mapping (``geocode_cache``) is keyed by query text alone, so the
# Redis prefix bump above does not retire it — a coordinate admitted by the old
# chain would keep answering for as long as the row exists. The durable key
# therefore carries the same version, which retires the old rows' meaning with
# no data migration: the key is opaque text. Keep in step with _CACHE_PREFIX.
_DB_KEY_VERSION = "v7:"


def _cache_key(text: str) -> str:
    digest = sha256(normalize_vietnamese_text(text).encode("utf-8")).hexdigest()[:32]
    return f"{_CACHE_PREFIX}{digest}"


def _viewbox_focus(viewbox: str | None) -> tuple[float, float] | None:
    """Convert the caller's ``viewbox`` into Vietmap's ``focus`` centre point.

    ``viewbox`` is ``"x1,y1,x2,y2"`` as lon,lat (left/top/right/bottom); Vietmap
    takes a single ``lat,lng`` point. The centre steers Vietmap's ranking the way
    the box steered the provider this replaced, so ``active_area_viewbox`` stays
    the single source of truth for the candidate's region. ``None`` when there is
    no box, an unparseable one, or a degenerate point — Vietmap then ranks
    nationally.
    """
    if not viewbox:
        return None
    parts = viewbox.split(",")
    if len(parts) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(part) for part in parts)
    except ValueError:
        return None
    lat = (y1 + y2) / 2
    lng = (x1 + x2) / 2
    return lat, lng


async def _db_lookup(query: str) -> tuple[tuple[float, float] | None, bool]:
    """Consult the durable mapping first — before any provider HTTP call.

    Returns ``(coords, found)``. A coordinate row answers the lookup directly;
    a NULL-coordinate row is a recorded miss — unless it is older than the
    negative TTL, in which case it is treated as absent so improving provider
    coverage is picked up. Any database problem is a cache miss, never an
    error: the providers below still run.
    """
    try:
        async with async_session() as db:
            row = (
                await db.execute(
                    select(
                        GeocodeCache.latitude,
                        GeocodeCache.longitude,
                        GeocodeCache.updated_at,
                    ).where(GeocodeCache.query == query)
                )
            ).first()
    except Exception:  # noqa: BLE001 — the mapping is decoration, never a failure
        logger.warning("geocode db lookup failed", exc_info=True)
        return None, False
    if row is None:
        return None, False
    lat, lng, updated_at = row
    if lat is None or lng is None:
        ttl = get_settings().geocoder_negative_ttl_seconds
        stale = updated_at is not None and (
            datetime.now(UTC) - updated_at
        ).total_seconds() > ttl
        return (None, False) if stale else (None, True)
    return (float(lat), float(lng)), True


async def _db_store(
    query: str, coords: tuple[float, float] | None, provider: str | None
) -> None:
    """Write through the resolved answer (or the miss) to the durable mapping.

    Never raises: a mapping write failure must not fail the geocode call.
    """
    try:
        async with async_session() as db:
            await db.execute(
                pg_insert(GeocodeCache)
                .values(
                    query=query,
                    latitude=coords[0] if coords else None,
                    longitude=coords[1] if coords else None,
                    provider=provider,
                )
                .on_conflict_do_update(
                    index_elements=[GeocodeCache.query],
                    set_={
                        "latitude": coords[0] if coords else None,
                        "longitude": coords[1] if coords else None,
                        "provider": provider,
                        "updated_at": datetime.now(UTC),
                    },
                )
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — the mapping is decoration, never a failure
        logger.warning("geocode db store failed", exc_info=True)


async def geocode(
    query: str,
    *,
    viewbox: str | None = None,
    providers: "GeoRuntimeConfig | None" = None,
    precision: Literal["area", "point"] = "area",
) -> tuple[float, float] | None:
    """Resolve ``query`` to ``(lat, lng)``; ``None`` when unresolved.

    Never raises. A warm cache — positive or negative — performs no HTTP call.
    The query is passed to each provider VERBATIM: there is no relaxation, and a
    miss is cached under the query the caller passed.

    ``providers`` (the admin-editable credential bundle) enables the keyed hops,
    tried in order and only when the previous one misses: **Google** first, then
    **Vietmap**. Google leads because it was measurably better on the plants
    this bot serves (0.92 km median error against OSM ground truth vs Vietmap's
    2.74 km); Vietmap stays as the fallback for when Google is over quota. With
    neither key configured the chain has no members and every lookup is a miss —
    the deliberate trade for dropping the keyless provider (see the module
    docstring). Each hop runs exactly once and is fail-open.

    ``viewbox`` ("x1,y1,x2,y2" as lon,lat, left/top/right/bottom) is the
    candidate's region. It becomes Vietmap's ``focus`` centre point (see
    ``_viewbox_focus``) — a ranking bias, never a filter, so a genuinely-far
    area ("Hà Nội") still resolves to the city the candidate named rather than
    to whatever happens to sit inside the box. Google takes no region bias.

    ``precision`` decides what an answer is allowed to be. ``"area"`` (default)
    accepts a ward or city answer — enough to RANK projects near a candidate.
    ``"point"`` makes the Google hop refuse an answer whose ``types`` name a
    populated place or an administrative boundary, so a street address can never
    resolve to the middle of a city (the 2026-10-03 incident). Vietmap's payload
    exposes no equivalent flag, so a ``"point"`` caller gets the guard from the
    first hop only; the factory path does not rely on it either way, because
    every candidate there must survive the containment check.
    """
    text = query.strip()
    if not text:
        return None
    key = _cache_key(text)
    cached = await cache_get_json(key)
    if isinstance(cached, dict):
        if "lat" in cached and "lng" in cached:
            try:
                return float(cached["lat"]), float(cached["lng"])
            except (TypeError, ValueError):
                pass  # a corrupt entry falls through to a fresh lookup
        elif "miss" in cached:
            return None
    settings = get_settings()
    if not settings.geocoder_enabled:
        await cache_set_json(key, {"miss": True}, settings.geocoder_negative_ttl_seconds)
        return None
    # The durable mapping answers before any provider call; Redis answered only
    # when it held a fresh copy. A recorded (fresh) miss ends the walk here.
    db_query = f"{_DB_KEY_VERSION}{normalize_vietnamese_text(text)}"
    db_coords, db_found = await _db_lookup(db_query)
    if db_found:
        if db_coords is not None:
            await cache_set_json(
                key,
                {"lat": db_coords[0], "lng": db_coords[1]},
                settings.geocoder_cache_ttl_seconds,
            )
            return db_coords
        return None
    # Keyed hops, in the measured order (see ``KEYED_GEO_HOPS``). Each runs at
    # most once, on the caller's exact text only, and fail-open. The query is
    # NOT relaxed for them: a keyed provider answers a partial query with a
    # confident wrong match rather than nothing ("tran phu" resolves to Phường
    # Trần Phú, Hà Tĩnh), so dropping components would trade a miss for a wrong
    # answer.
    focus = _viewbox_focus(viewbox)
    for hop in KEYED_GEO_HOPS:
        api_key = getattr(providers, hop.key_field, "") if providers is not None else ""
        if not api_key:
            continue
        extra: dict[str, object] = {}
        if hop.accepts_focus and focus is not None:
            extra["focus"] = focus
        if hop.rejects_coarse and precision == "point":
            extra["require_point"] = True
        try:
            hit = await hop.fetch(
                text,
                api_key=api_key,
                timeout_seconds=settings.geocoder_timeout_seconds,
                **extra,
            )
        except Exception:  # noqa: BLE001 — a hop must never break the chain
            logger.warning("geocode hop failed provider=%s", hop.name, exc_info=True)
            continue
        if hit is None:
            continue
        await _db_store(db_query, hit, hop.name)
        await cache_set_json(
            key, {"lat": hit[0], "lng": hit[1]}, settings.geocoder_cache_ttl_seconds
        )
        return hit
    await _db_store(db_query, None, None)
    await cache_set_json(key, {"miss": True}, settings.geocoder_negative_ttl_seconds)
    return None
