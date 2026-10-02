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
from hashlib import sha256

from app.core.cache import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.core.http import get_http_client
from app.shared.domain.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)

# One process-scoped httpx client for the geocoder; the name keys its pool.
_CLIENT_NAME = "geocoder"
_CACHE_PREFIX = "geo:geocode:v2:"
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


async def geocode(query: str) -> tuple[float, float] | None:
    """Resolve ``query`` to ``(lat, lng)``; ``None`` when unresolved.

    Never raises. A warm cache — positive or negative — performs no HTTP call.
    A query the geocoder cannot resolve is retried with its leading components
    dropped, up to ``_MAX_QUERY_ATTEMPTS`` attempts; a hit from any attempt is
    cached under the query the caller passed.
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
            response = await client.get(
                "/search",
                params={
                    "q": attempt,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "vn",
                    "accept-language": "vi",
                },
            )
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
        await cache_set_json(
            key, {"lat": lat, "lng": lng}, settings.geocoder_cache_ttl_seconds
        )
        return lat, lng
    await cache_set_json(key, {"miss": True}, settings.geocoder_negative_ttl_seconds)
    return None
