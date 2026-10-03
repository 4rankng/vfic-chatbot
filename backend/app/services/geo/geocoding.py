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
first, and every attempt stays inside the address's own hierarchy.

Precision: relaxing answers with a coarser point, which is a different
question depending on WHO is being placed. A candidate's own area only has to
rank projects ("rough enough to sort"), so ``precision="area"`` — the default —
keeps a ward or district hit. A project's work address is quoted back to
candidates as a road distance to a factory gate, so it runs
``precision="point"``: a hit that needed components dropped must then land on a
genuine point feature, and a populated-place or boundary centroid
(``_COARSE_PLACE_TYPES``) is refused. Dropping detail and still answering with
an area label means the provider resolved something nobody asked about, and a
miss is strictly better: the caller reports "chưa xác định được" instead of a
confident wrong distance.

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
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.core.db import async_session
from app.core.http import get_http_client
from app.models.geocode import GeocodeCache
from app.services.geo.providers import KEYED_GEO_HOPS
from app.shared.domain.text import normalize_vietnamese_text

if TYPE_CHECKING:
    from app.services.integration_settings.providers.geo import GeoRuntimeConfig

logger = logging.getLogger(__name__)

# One process-scoped httpx client for the geocoder; the name keys its pool.
_CLIENT_NAME = "geocoder"
# v6: the keyed hops were reordered by measurement — Google ahead of Vietmap
# (see ``KEYED_GEO_HOPS`` for the study). A coordinate is only as good as the
# chain that produced it, so a v5 entry — resolved Vietmap-first — no longer
# means the same thing as one resolved under the measured order. v5 was the
# ``precision="point"`` gate, itself a bump over v4 (the Vietmap reorder).
_CACHE_PREFIX = "geo:geocode:v6:"
# The DURABLE mapping (``geocode_cache``) is keyed by query text alone, so the
# Redis prefix bump above does not retire it — a coordinate admitted by the old
# chain would keep answering for as long as the row exists. The durable key
# therefore carries the same version, which retires the old rows' meaning with
# no data migration: the key is opaque text. Keep in step with _CACHE_PREFIX.
_DB_KEY_VERSION = "v6:"
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

# ``addresstype`` values that are a POPULATED PLACE or an ADMINISTRATIVE
# BOUNDARY — a label whose coordinate is the centroid of an area, not a place
# anyone can stand at. The 2026-10-03 incident: "Tầng 2, Công ty LG Electronics
# (LGE), KCN Tràng Duệ, An Phong, An Dương, Hải Phòng" matched nothing until
# the ladder had dropped every leading component and asked for "TP. Hải Phòng",
# which Nominatim answers with the city centroid (20.8831, 106.6790). That
# centroid was stored as the factory gate, so a candidate in Phường An Biên was
# told KCN Tràng Duệ — 13.6 km away by road — was "1.5 km" away. A relaxed hit
# on one of these is a miss wearing a coordinate; ``precision="point"`` refuses
# it. The ladder still admits genuine point features (OSM tags KCN Đình Vũ
# ``industrial``), which is how a precise answer survives.
_COARSE_PLACE_TYPES = frozenset(
    {
        "administrative",
        "borough",
        "city",
        "city_district",
        "commune",
        "county",
        "district",
        "hamlet",
        "island",
        "municipality",
        "neighbourhood",
        "province",
        "quarter",
        "region",
        "state",
        "suburb",
        "town",
        "village",
        "ward",
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
    precision: Literal["area", "point"] = "area",
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

    ``precision`` decides what a relaxed hit is allowed to be. ``"area"``
    (default) keeps a ward/district hit — enough to RANK projects near a
    candidate. ``"point"`` refuses a relaxed hit that landed on a populated
    place or administrative centroid, so a factory address can never resolve to
    the middle of a city (see ``_COARSE_PLACE_TYPES`` for the incident this
    closes). The exact-text attempt and both keyed providers are unaffected
    either way: a precise answer is a precise answer.
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
    # most once, on the caller's exact text only, fail-open; the Nominatim
    # ladder below then runs exactly as it would without any credential. The
    # ladder is deliberately NOT offered to these providers: a keyed provider
    # answers a partial query with a confident wrong match rather than nothing
    # ("tran phu" resolves to Phường Trần Phú, Hà Tĩnh), so relaxing for them
    # would trade a miss for a wrong answer.
    focus = _viewbox_focus(viewbox)
    for hop in KEYED_GEO_HOPS:
        api_key = getattr(providers, hop.key_field, "") if providers is not None else ""
        if not api_key:
            continue
        try:
            hit = await hop.fetch(
                text,
                api_key=api_key,
                timeout_seconds=settings.geocoder_timeout_seconds,
                **({"focus": focus} if hop.accepts_focus and focus is not None else {}),
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
    # Relax the query only after the exact text failed; the first attempt is
    # always the caller's own string, so a precise address stays precise.
    for position, attempt in enumerate(_query_variants(text)):
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
            matches = response.json()
            if not matches:
                # An empty result is the NORMAL answer for an address Nominatim
                # does not index — a full Vietnamese factory address, most of the
                # time. It is a step in the walk, not a failure, so it must not
                # log a warning with a traceback; that turned every relaxed
                # attempt into a WARNING and drowned the real failures.
                logger.debug("geocode no match query=%s", attempt)
                continue
            item = matches[0]
            kind = item["addresstype"] if "addresstype" in item else ""
            if isinstance(kind, str) and kind in _BLOCKED_ADDRESS_TYPES:
                logger.debug("geocode street-level match rejected query=%s type=%s", attempt, kind)
                continue
            # A relaxed hit on an area label resolves a coarser question than
            # the one asked. "point" callers (a factory gate, quoted to a
            # candidate as a road distance) must not store that: it is a miss
            # wearing a coordinate, and the miss is what keeps the reply honest.
            if position and precision == "point" and kind in _COARSE_PLACE_TYPES:
                logger.debug(
                    "geocode coarse relaxed match rejected query=%s type=%s", attempt, kind
                )
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
