"""Free geocoding client for project work addresses and candidate areas.

Why this exists: candidates ask "dự án nào gần nhà tôi?" and nothing in the
system carried coordinates. The candidate's area already arrives every turn
(``leads.region``/``living_area``) and the project's work address is in the KB
brief, so one forward geocode per distinct string turns both into a distance.

Provider: Nominatim-compatible ``GET /search`` (``format=jsonv2``). The default
base URL is the public Nominatim instance — free, no key, but its usage policy
caps at 1 request/second and requires a descriptive User-Agent, so this client
throttles globally at ``geocoder_min_interval_seconds`` (default 1.0) and sends
``geocoder_user_agent``. Repointing ``geocoder_base_url`` at a self-hosted
instance needs no code change.

Caching: two tiers keyed by the accent-insensitive normalized query.
``geo:geocode:v2:<sha256[:32]>`` holds either ``{"lat": …, "lng": …}`` for
``geocoder_cache_ttl_seconds`` (30 days) or ``{"miss": true}`` for
``geocoder_negative_ttl_seconds`` (6 hours). The negative tier is why a repeated
unresolvable area costs no network call. The key carries its version because
the resolution rules (the relaxation ladder and the street-match gate below)
changed what a stored value means; a bump retires entries written under the
previous rules instead of serving them for their full TTL.

Relaxation: Nominatim's free-form search returns nothing when ANY
comma-separated component is not a place it knows, which makes a full Vietnamese
work address ("Tầng 2, Công ty LG Electronics, KCN Tràng Duệ, An Phong, An
Dương, Hải Phòng") unresolvable while its own suffix ("An Dương, Hải Phòng")
resolves. ``geocode`` therefore retries its suffixes with leading components
dropped, capped at ``_MAX_QUERY_ATTEMPTS``; the exact text is always tried
first, and every attempt stays inside the address's own hierarchy. A hit from a
relaxed attempt is a coarser (ward/district/city) point, so ``distance_km``
downstream is an approximate straight-line figure at the ~10 km scale — enough
to rank projects near a candidate, not a routing distance.

Fail-open by contract: an outage, timeout, non-200, or malformed payload
returns ``None`` and logs — never raises. Callers (project ingest, the catalog
tool) treat ``None`` as "no coordinates", which degrades to today's behavior.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.core.db import async_session
from app.core.http import get_http_client
from app.models.geocode import GeocodeCache
from app.services.geo.providers import google_geocode, vietmap_geocode
from app.shared.domain.text import normalize_vietnamese_text

if TYPE_CHECKING:
    from app.services.integration_settings.providers.geo import GeoRuntimeConfig

logger = logging.getLogger(__name__)

# One process-scoped httpx client for the geocoder; the name keys its pool.
_CLIENT_NAME = "geocoder"
# v4: Vietmap became the primary hop (v3 was Google-first). A v3 entry holds a
# coordinate resolved under a different chain — the same address can legitimately
# resolve differently once the leading provider changes — so the bump retires
# them instead of serving the old order's answer for its full 30-day TTL.
_CACHE_PREFIX = "geo:geocode:v4:"
# Nominatim's free-form search rejects the WHOLE query when any comma-separated
# component is not a place it knows: "Tầng 2, Công ty LG Electronics, KCN Tràng
# Duệ, An Phong, An Dương, Hải Phòng" finds nothing while "An Dương, Hải Phòng"
# resolves. Vietnamese addresses are written most-specific first, so the
# relaxation that keeps the address's own hierarchy is dropping LEADING
# components. The cap bounds the worst-case latency of one cold lookup (each
# attempt is throttled to the provider's 1 req/s floor); a hit is cached for 30
# days, so the walk happens once per distinct address.
_MAX_QUERY_ATTEMPTS = 5

# ``addresstype`` values that describe a street/exact address rather than a
# place. Nominatim fuzzy-matches a relaxed component against a street name —
# "Huyện An Dương (xã An Phong), TP. Hải Phòng" resolved to a road in Hải Dương
# ~35 km from the industrial park — which would answer "gần nhà" with a wrong
# origin. Such a hit is rejected and the walk continues to a coarser, real place
# (or to a plain miss); a legitimate street-only address therefore resolves at
# its district/city level instead, which is the precision a distance ranking
# actually needs.
_BLOCKED_ADDRESS_TYPES = frozenset(
    {
        "address",
        "building",
        "cycleway",
        "footway",
        "house",
        "living_street",
        "path",
        "pedestrian",
        "postcode",
        "residential",
        "road",
        "service",
        "steps",
        "track",
    }
)

# Serializes outbound calls and enforces the provider's minimum interval across
# the whole process (ingest workers and the web process each hold their own).
# Allocated lazily inside the running loop, exactly as ``app.core.http._get_lock``.
_THROTTLE_LOCK: asyncio.Lock | None = None
_last_call_at: float = 0.0


def _get_throttle_lock() -> asyncio.Lock:
    global _THROTTLE_LOCK
    if _THROTTLE_LOCK is None:
        _THROTTLE_LOCK = asyncio.Lock()
    return _THROTTLE_LOCK


def _cache_key(text: str) -> str:
    digest = sha256(normalize_vietnamese_text(text).encode("utf-8")).hexdigest()[:32]
    return f"{_CACHE_PREFIX}{digest}"


def _viewbox_focus(viewbox: str | None) -> tuple[float, float] | None:
    """Convert a Nominatim ``viewbox`` into Vietmap's ``focus`` centre point.

    ``viewbox`` is ``"x1,y1,x2,y2"`` as lon,lat (left/top/right/bottom);
    Vietmap takes a single ``lat,lng`` point. The centre steers ranking the same
    way the box steers Nominatim's, so the same region signal serves both hops
    and ``active_area_viewbox`` stays the single source of truth. ``None`` when
    there is no box, an unparseable one, or a degenerate point — Vietmap then
    ranks nationally, exactly as Nominatim does with no viewbox.
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


def _query_variants(text: str) -> tuple[str, ...]:
    """The query itself, then its suffixes with leading components dropped.

    Every variant is a suffix of the original's comma-separated components, so a
    relaxed query can only ever resolve to a coarser place the address itself
    named — never a different district the caller did not mention.
    """
    parts = [part.strip() for part in text.split(",")]
    variants: list[str] = []
    for start in range(len(parts)):
        candidate = ", ".join(part for part in parts[start:] if part)
        if candidate and candidate not in variants:
            variants.append(candidate)
        if len(variants) >= _MAX_QUERY_ATTEMPTS:
            break
    return tuple(variants) or (text,)


async def _throttle(min_interval: float) -> None:
    """Hold the outbound call so consecutive requests are ``min_interval`` apart."""
    global _last_call_at
    async with _get_throttle_lock():
        now = time.monotonic()
        wait = _last_call_at + min_interval - now
        if wait > 0:
            await asyncio.sleep(wait)
            now = time.monotonic()
        _last_call_at = now


async def geocode(
    query: str,
    *,
    viewbox: str | None = None,
    providers: "GeoRuntimeConfig | None" = None,
) -> tuple[float, float] | None:
    """Resolve ``query`` to ``(lat, lng)``; ``None`` when unresolved.

    Never raises. A warm cache — positive or negative — performs no HTTP call.
    A query the geocoder cannot resolve is retried with its leading components
    dropped, up to ``_MAX_QUERY_ATTEMPTS`` attempts; a hit from any attempt is
    cached under the query the caller passed.

    ``providers`` (the admin-editable credential bundle) enables the keyed
    hops, tried in order and only when the previous one misses: **Vietmap**
    first — the Vietnam-native provider that indexes the local landmarks OSM
    lacks ("Núi Đèo", KCN names), so a correct answer lands on the first hop
    rather than after a free provider confidently returns the wrong one — then
    **Google** for international coverage, then the keyless **Nominatim**
    ladder. Vietmap deliberately receives only ``text``: it answers a partial
    query with a confident wrong match rather than nothing, so the relaxation
    ladder below stays confined to the Nominatim hop. Each keyed hop runs
    exactly once and is fail-open; a miss on them is not cached apart — the
    negative cache below covers the whole chain.

    ``viewbox`` ("x1,y1,x2,y2" as lon,lat, left/top/right/bottom) biases the
    Nominatim ranking toward that box without excluding outside results — the
    Nominatim-recommended way to steer a bare name ("Núi Đèo") at the region
    the caller operates in. Deliberately bias-only, never ``bounded=1``: a hard
    box makes a genuinely-far area ("Hà Nội") resolve to whatever road happens
    to sit inside the box instead of the city the candidate named.
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
    db_query = normalize_vietnamese_text(text)
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
    # Primary hop: Vietmap is Vietnam-native and indexes the local landmarks
    # ("Núi Đèo", KCN names, ward-level entries) that OSM misses, so a correct
    # answer lands here rather than after a free provider confidently returns
    # the wrong one. Exactly once, on the caller's exact text, fail-open.
    if providers is not None and providers.vietmap_api_key:
        hit = await vietmap_geocode(
            text,
            api_key=providers.vietmap_api_key,
            focus=_viewbox_focus(viewbox),
            timeout_seconds=settings.geocoder_timeout_seconds,
        )
        if hit is not None:
            await _db_store(db_query, hit, "vietmap")
            await cache_set_json(
                key,
                {"lat": hit[0], "lng": hit[1]},
                settings.geocoder_cache_ttl_seconds,
            )
            return hit
    # Second hop: Google covers the international addresses Vietmap does not.
    # One exact-string attempt, fail-open; on a miss the Nominatim ladder below
    # runs exactly as without any credential.
    if providers is not None and providers.google_maps_api_key:
        hit = await google_geocode(
            text,
            api_key=providers.google_maps_api_key,
            timeout_seconds=settings.geocoder_timeout_seconds,
        )
        if hit is not None:
            await _db_store(db_query, hit, "google")
            await cache_set_json(
                key,
                {"lat": hit[0], "lng": hit[1]},
                settings.geocoder_cache_ttl_seconds,
            )
            return hit
    # Relax the query only after the exact text failed; the first attempt is
    # always the caller's own string, so a precise address stays precise.
    for attempt in _query_variants(text):
        try:
            await _throttle(settings.geocoder_min_interval_seconds)
            client = await get_http_client(
                _CLIENT_NAME,
                base_url=settings.geocoder_base_url,
                timeout=settings.geocoder_timeout_seconds,
                headers={"User-Agent": settings.geocoder_user_agent},
            )
            params = {
                "q": attempt,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "vn",
                "accept-language": "vi",
            }
            if viewbox:
                params["viewbox"] = viewbox
            response = await client.get("/search", params=params)
            if response.status_code != 200:
                raise ValueError(f"geocoder status {response.status_code}")
            item = response.json()[0]
            kind = item["addresstype"] if "addresstype" in item else ""
            if isinstance(kind, str) and kind in _BLOCKED_ADDRESS_TYPES:
                logger.debug("geocode street-level match rejected query=%s type=%s", attempt, kind)
                continue
            lat = float(item["lat"])
            lng = float(item["lon"])
        except Exception:  # noqa: BLE001 — geocoding is decoration, never a failure
            logger.warning("geocode attempt failed query=%s", attempt, exc_info=True)
            continue
        await _db_store(db_query, (lat, lng), "nominatim")
        await cache_set_json(
            key, {"lat": lat, "lng": lng}, settings.geocoder_cache_ttl_seconds
        )
        return lat, lng
    await _db_store(db_query, None, None)
    await cache_set_json(key, {"miss": True}, settings.geocoder_negative_ttl_seconds)
    return None
