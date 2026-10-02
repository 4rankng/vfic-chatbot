"""Road-distance estimates for the catalog tools: matrix providers + DB cache.

One row per geocoded origin → destination coordinate pair in the
``distance_estimate`` table: the tools read the durable mapping before any
provider HTTP call, so a pair is estimated once and served from the database
afterwards. The ladder is Vietmap Matrix v4 first (the primary geocoder, a
Vietnamese road network), then Google's Distance Matrix — both keyed hops,
both optional.

Fail-open end to end: no configured key, an outage, or a malformed payload
leaves an entry ``None`` and the caller falls back to its straight-line
number. This module never raises; failed estimates are never stored, so the
next turn retries them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import async_session
from app.models.distance_estimate import DistanceEstimate
from app.services.geo.providers import google_distance_matrix, vietmap_matrix

if TYPE_CHECKING:
    from app.services.integration_settings.providers.geo import GeoRuntimeConfig

logger = logging.getLogger(__name__)

# 5 decimal places ≈ 1.1 m — finer than any provider's own accuracy, so the
# key only has to collapse the same geocoded point to the same row.
_KEY_FORMAT = "{:.5f}"


def _pair_key(point: tuple[float, float]) -> str:
    return f"{_KEY_FORMAT.format(point[0])},{_KEY_FORMAT.format(point[1])}"


async def _db_lookup(
    origin_key: str, destination_keys: list[str]
) -> dict[str, tuple[float, float | None]]:
    """Cached estimates for the pair set; any database problem is a miss."""
    if not destination_keys:
        return {}
    try:
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(
                        DistanceEstimate.destination_key,
                        DistanceEstimate.distance_km,
                        DistanceEstimate.duration_s,
                    ).where(
                        DistanceEstimate.origin_key == origin_key,
                        DistanceEstimate.destination_key.in_(destination_keys),
                    )
                )
            ).all()
    except Exception:  # noqa: BLE001 — the cache is decoration, never a failure
        logger.warning("distance estimate db lookup failed", exc_info=True)
        return {}
    return {str(key): (float(km), float(seconds) if seconds is not None else None) for key, km, seconds in rows}


async def _db_store(
    origin_key: str,
    entries: dict[str, tuple[float, float | None, str]],
) -> None:
    """Write through every successful estimate; never raises."""
    if not entries:
        return
    try:
        async with async_session() as db:
            for destination_key, (km, seconds, provider) in entries.items():
                await db.execute(
                    pg_insert(DistanceEstimate)
                    .values(
                        origin_key=origin_key,
                        destination_key=destination_key,
                        distance_km=km,
                        duration_s=seconds,
                        provider=provider,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            DistanceEstimate.origin_key,
                            DistanceEstimate.destination_key,
                        ],
                        set_={
                            "distance_km": km,
                            "duration_s": seconds,
                            "provider": provider,
                            "updated_at": datetime.now(UTC),
                        },
                    )
                )
            await db.commit()
    except Exception:  # noqa: BLE001 — the cache is decoration, never a failure
        logger.warning("distance estimate db store failed", exc_info=True)


async def estimate_distances(
    origin: tuple[float, float],
    destinations: list[tuple[float, float]],
    *,
    providers: GeoRuntimeConfig,
) -> list[tuple[float, float | None] | None]:
    """Road estimates aligned to ``destinations``; ``None`` where unavailable.

    Order: the durable mapping first, then one Vietmap Matrix v4 call for the
    remaining pairs, then Google's Distance Matrix for whatever Vietmap left
    empty (a keyed hop may be absent — the ladder degrades in place).
    """
    if not destinations:
        return []
    origin_key = _pair_key(origin)
    destination_keys = [_pair_key(point) for point in destinations]
    cached = await _db_lookup(origin_key, destination_keys)
    results: list[tuple[float, float | None] | None] = [
        cached.get(key) for key in destination_keys
    ]

    pending = [index for index, value in enumerate(results) if value is None]
    for provider_name, api_key, fetch in (
        ("vietmap", providers.vietmap_api_key, vietmap_matrix),
        ("google", providers.google_maps_api_key, google_distance_matrix),
    ):
        if not pending or not api_key:
            continue
        try:
            fetched = await fetch(
                origin, [destinations[index] for index in pending], api_key=api_key
            )
        except Exception:  # noqa: BLE001 — a hop must never break the estimate
            logger.warning("distance matrix hop failed provider=%s", provider_name, exc_info=True)
            continue
        if fetched is None:
            continue  # whole-call failure → the next hop gets its turn
        still_pending: list[int] = []
        stored: dict[str, tuple[float, float | None, str]] = {}
        for slot, value in zip(pending, fetched):
            if value is None:
                still_pending.append(slot)
                continue
            km, seconds = value
            results[slot] = (km, seconds)
            stored[destination_keys[slot]] = (km, seconds, provider_name)
        pending = still_pending
        await _db_store(origin_key, stored)

    return results
