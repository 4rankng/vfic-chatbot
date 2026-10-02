"""Google geocoding adapter for the distance feature.

Nominatim/OSM lacks many Vietnamese landmarks — the 2026-10-02 incident
resolved the bare name "Núi Đèo" to a same-named feature ~120 km away because
OSM has no Núi Đèo in Hải Phòng at all. Google's Geocoding API indexes local
landmark names. It is optional (used only when a key is configured) and
fail-open: an outage degrades to the Nominatim fallback instead of failing
the turn.

Map4D was evaluated first (a Vietnamese provider with local landmark data)
but its API proved unreachable from the prod host (connection timeout,
02 Oct), so it was removed rather than shipped as a dead first hop.
"""

from __future__ import annotations

import logging

from app.core.http import get_http_client

logger = logging.getLogger(__name__)

_GOOGLE_CLIENT = "geocoder-google"


async def google_geocode(
    query: str,
    *,
    api_key: str,
    timeout_seconds: float = 3.0,
) -> tuple[float, float] | None:
    """Return ``(lat, lng)`` for the first result of Google's Geocoding API.

    Fail-open: a network error, non-200, a non-``OK`` status (REQUEST_DENIED,
    OVER_QUERY_LIMIT, ZERO_RESULTS), or a malformed payload is a miss.
    """
    try:
        client = await get_http_client(
            _GOOGLE_CLIENT,
            base_url="https://maps.googleapis.com",
            timeout=timeout_seconds,
        )
        response = await client.get(
            "/maps/api/geocode/json", params={"address": query, "key": api_key}
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        if payload.get("status") != "OK":
            return None
        results = payload.get("results") or []
        location = (results[0].get("geometry") or {}).get("location") or {}
        return float(location["lat"]), float(location["lng"])
    except Exception:  # noqa: BLE001 — geocoding is decoration, never a failure
        logger.warning("google geocode failed query=%s", query, exc_info=True)
        return None
