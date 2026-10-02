"""Keyed geocoding adapters for the distance feature.

Vietmap is the primary hop: a Vietnam-native provider that indexes local
landmark names, industrial parks and per-ward data OSM simply does not carry.
Google is the second hop for the international coverage Vietmap lacks, and
Nominatim stays the terminal, keyless, always-available fallback.

Both keyed adapters are optional (used only when a key is configured) and
fail-open: an outage degrades to the next hop instead of failing the turn.

Map4D was evaluated first (a Vietnamese provider with local landmark data)
but its API proved unreachable from the prod host (connection timeout,
02 Oct), so it was removed rather than shipped as a dead first hop.
"""

from __future__ import annotations

import logging

from app.core.http import get_http_client

logger = logging.getLogger(__name__)

_GOOGLE_CLIENT = "geocoder-google"
_VIETMAP_CLIENT = "geocoder-vietmap"
_VIETMAP_BASE_URL = "https://maps.vietmap.vn"
# Vietmap's own recommendation for the 2025 ward-merger migration: the new
# 2-level admin format at the top level, the legacy 3-level text in ``data_old``.
# One call yields both, so Migrate-Address is never needed.
_VIETMAP_DISPLAY_TYPE = 5


async def vietmap_geocode(
    query: str,
    *,
    api_key: str,
    focus: tuple[float, float] | None = None,
    timeout_seconds: float = 3.0,
) -> tuple[float, float] | None:
    """Return ``(lat, lng)`` for the first Vietmap match of ``query``.

    ``query`` MUST be the caller's exact original string. Vietmap does not
    return an empty array for a partial query as its docs suggest — it returns
    a confident, wrong match ("tran phu" resolves to *Phường Trần Phú, Hà
    Tĩnh*). A relaxed address variant must never reach this function; the
    relaxation ladder is confined to the Nominatim hop.

    Text→coordinates is two calls: ``search/v4`` yields a ``ref_id`` with no
    coordinates, ``place/v4`` resolves it. The ``ref_id`` is opaque and its
    prefix differs per endpoint, so it is passed through verbatim.

    ``focus`` is a ``(lat, lng)`` point that reorders results; it does not
    filter. Fail-open: a network error, non-200, empty match set, a missing
    ``ref_id``, or coordinates-less place payload is a miss.
    """
    try:
        client = await get_http_client(
            _VIETMAP_CLIENT,
            base_url=_VIETMAP_BASE_URL,
            timeout=timeout_seconds,
        )
        params: dict[str, str] = {
            "apikey": api_key,
            "text": query,
            "display_type": str(_VIETMAP_DISPLAY_TYPE),
        }
        if focus is not None:
            params["focus"] = f"{focus[0]},{focus[1]}"
        search = await client.get("/api/search/v4", params=params)
        if search.status_code != 200:
            return None
        matches = search.json()
        if not matches:
            return None
        ref_id = matches[0].get("ref_id")
        if not ref_id:
            return None
        place = await client.get(
            "/api/place/v4", params={"apikey": api_key, "refid": ref_id}
        )
        if place.status_code != 200:
            return None
        payload = place.json()
        lat, lng = payload.get("lat"), payload.get("lng")
        if lat is None or lng is None:
            return None
        return float(lat), float(lng)
    except Exception:  # noqa: BLE001 — geocoding is decoration, never a failure
        logger.warning("vietmap geocode failed query=%s", query, exc_info=True)
        return None


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


# One process-scoped httpx client for the distance-matrix providers; the name
# keys its pool (separate from the geocoder's so a slow matrix call never
# delays an in-flight geocode).
_DISTANCE_CLIENT = "distance-matrix"
# Per-call budget: documented latencies are sub-second, and every caller has a
# straight-line fallback, so a slow provider degrades the number instead of
# the turn.
_MATRIX_TIMEOUT_S = 4.0


async def vietmap_matrix(
    origin: tuple[float, float],
    destinations: list[tuple[float, float]],
    *,
    api_key: str,
    timeout_seconds: float = _MATRIX_TIMEOUT_S,
) -> list[tuple[float, float | None] | None] | None:
    """One Matrix v4 call: ``(km, seconds-or-None)`` per destination.

    ``None`` (the whole call failed) versus a list with ``None`` entries (the
    call succeeded but a cell had no route) is the distinction the caller
    needs: only the whole-call miss falls through to the next provider.

    Endpoint and payload follow the published spec
    (``maps.vietmap.vn/api/matrix/v4``): points as ``lat,lng`` pairs, one
    source (index 0 = the origin), destinations as the remaining indices,
    ``distances`` in meters, ``durations`` in seconds, ``code == "OK"``.
    Fail-open: a network error, non-200, non-OK code, or a row whose length
    disagrees with the request is ``None``.
    """
    if not destinations:
        return []
    try:
        client = await get_http_client(
            _DISTANCE_CLIENT,
            base_url=_VIETMAP_BASE_URL,
            timeout=timeout_seconds,
        )
        points = [origin, *destinations]
        params: list[tuple[str, str]] = [
            ("apikey", api_key),
            ("vehicle", "car"),
            ("sources", "0"),
            (
                "destinations",
                ";".join(str(index) for index in range(1, len(points))),
            ),
        ]
        params.extend(("point", f"{lat},{lng}") for lat, lng in points)
        response = await client.get("/api/matrix/v4", params=params)
        if response.status_code != 200:
            return None
        payload = response.json()
        if payload.get("code") != "OK":
            return None
        distances = payload.get("distances") or []
        durations = payload.get("durations") or []
        distance_row = distances[0] if distances else None
        duration_row = durations[0] if durations else None
        if distance_row is None or len(distance_row) != len(destinations):
            return None
        estimates: list[tuple[float, float | None] | None] = []
        for index, meters in enumerate(distance_row):
            if meters is None:
                estimates.append(None)
                continue
            seconds = (
                duration_row[index]
                if duration_row is not None and index < len(duration_row)
                else None
            )
            estimates.append(
                (float(meters) / 1000.0, float(seconds) if seconds is not None else None)
            )
        return estimates
    except Exception:  # noqa: BLE001 — distance is decoration, never a failure
        logger.warning("vietmap matrix failed", exc_info=True)
        return None


async def google_distance_matrix(
    origin: tuple[float, float],
    destinations: list[tuple[float, float]],
    *,
    api_key: str,
    timeout_seconds: float = _MATRIX_TIMEOUT_S,
) -> list[tuple[float, float | None] | None] | None:
    """One Distance Matrix call: ``(km, seconds-or-None)`` per destination.

    Same contract as :func:`vietmap_matrix`: ``None`` means the whole call
    failed; a list may carry ``None`` entries for cells Google resolved as
    ``ZERO_RESULTS``/``NOT_FOUND``. Fail-open on a network error, non-200,
    non-``OK`` top-level status, or a row length that disagrees with the
    request.
    """
    if not destinations:
        return []
    try:
        client = await get_http_client(
            _DISTANCE_CLIENT,
            base_url="https://maps.googleapis.com",
            timeout=timeout_seconds,
        )
        response = await client.get(
            "/maps/api/distancematrix/json",
            params={
                "origins": f"{origin[0]},{origin[1]}",
                "destinations": "|".join(f"{lat},{lng}" for lat, lng in destinations),
                "units": "metric",
                "key": api_key,
            },
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        if payload.get("status") != "OK":
            return None
        rows = payload.get("rows") or []
        elements = rows[0].get("elements") if rows else None
        if elements is None or len(elements) != len(destinations):
            return None
        estimates: list[tuple[float, float | None] | None] = []
        for element in elements:
            distance = (element or {}).get("distance") or {}
            if element.get("status") != "OK" or "value" not in distance:
                estimates.append(None)
                continue
            duration = (element.get("duration") or {}).get("value")
            estimates.append(
                (
                    float(distance["value"]) / 1000.0,
                    float(duration) if duration is not None else None,
                )
            )
        return estimates
    except Exception:  # noqa: BLE001 — distance is decoration, never a failure
        logger.warning("google distance matrix failed", exc_info=True)
        return None
