#!/usr/bin/env python3
"""Seed the verified-place gazetteer with the industrial parks this bot serves.

Every geocoder studied on 2026-10-03 failed to place at least one of these, and
one of them (KCN Nomura) is in none of their indexes. A row here is served
without any further verification — `factory_point.resolve_factory_point` returns
it before any provider call or containment check — so a wrong row is a wrong
distance served forever. A row is therefore only added when its coordinate came
from an INDEPENDENT source: an OpenStreetMap feature tagged for the park itself,
not a provider's guess. ``source`` records which, so a bad row is traceable.

Validating a row before it lands
--------------------------------
Reverse-geocode the candidate coordinate with Google and read the answer as a
person would — the point must sit in the place the address names. This is how
the three rows below were checked on 2026-10-03 (Google reverse, one call each):

    KCN Tràng Duệ  20.8619428, 106.5619529 -> "VH66+RPR, Unnamed, Road,
                   An Phong, Hải Phòng" .................. in Phường An Phong,
                   the ward the 4P/LGE address names.
    KCN VSIP       20.9095671, 106.7231804 -> "143-145 Đ. 19, KCN-DT-DV VSIP,
                   Hòa Bình, Hải Phòng" ... inside the park (its eastern end).
    KCN Đình Vũ    20.8267968, 106.7744652 -> "RQGF+XJ6, KCN Đình Vũ, Đông Hải,
                   Hải Phòng" ........................... in KCN Đình Vũ.

A candidate row whose reverse geocode names none of the places the address
names is not a gazetteer row — it is a provider guess, and the verified chain in
:mod:`app.services.geo.factory_point` is where guesses belong.

Idempotent: a park already present is left alone, so re-running after a
correction does not overwrite a human's edit. Use --force to re-point a park
that has moved or been corrected (upsert on ``name``).

Usage:
    python -m scripts.seed_geo_gazetteer [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import async_session, engine
from app.models.geo_gazetteer import GeoGazetteer

logger = logging.getLogger("seed_geo_gazetteer")

# Coordinates taken from OpenStreetMap features tagged for the parks themselves
# (`type=industrial` / a named `landuse`), not from any geocoding provider:
#   KCN Tràng Duệ ... Khu công nghiệp Tràng Duệ, Phường An Phong
#   KCN VSIP ........ Khu công nghiệp VSIP, Hậu Long, Phường Nam Triệu
#   KCN Đình Vũ ..... Khu Công Nghiệp Đình Vũ, Phường Đông Hải
# KCN Nomura / Nhật Bản is deliberately ABSENT: no provider indexes it and no
# independent coordinate was obtainable, so seeding one would put a guess behind
# an authority check that exists precisely to keep guesses out.
SEED = (
    {
        "name": "KCN Tràng Duệ",
        "aliases": "Khu công nghiệp Tràng Duệ,Tràng Duệ",
        "province": "Hải Phòng",
        "district": "An Dương",
        "ward": "An Phong",
        "latitude": 20.8619428,
        "longitude": 106.5619529,
        "source": "osm",
    },
    {
        "name": "KCN VSIP",
        "aliases": "Khu công nghiệp VSIP,VSIP",
        "province": "Hải Phòng",
        "district": "Thủy Nguyên",
        "ward": "Nam Triệu",
        "latitude": 20.9095671,
        "longitude": 106.7231804,
        "source": "osm",
    },
    {
        "name": "KCN Đình Vũ",
        "aliases": "Khu Công Nghiệp Đình Vũ,Đình Vũ",
        "province": "Hải Phòng",
        "district": "Hồng Bàng",
        "ward": "Đông Hải",
        "latitude": 20.8267968,
        "longitude": 106.7744652,
        "source": "osm",
    },
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-point parks that already exist (overwrites a human's correction)",
    )
    return parser.parse_args(argv)


async def run(*, force: bool) -> int:
    inserted = 0
    kept = 0
    try:
        async with async_session() as db:
            for row in SEED:
                existing = (
                    await db.execute(
                        select(GeoGazetteer).where(
                            GeoGazetteer.name == row["name"]
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None and not force:
                    kept += 1
                    continue
                values = {
                    **row,
                    "verified_by": "seed:osm",
                    "is_active": True,
                    "updated_at": datetime.now(UTC),
                }
                if existing is not None:
                    await db.execute(
                        pg_insert(GeoGazetteer)
                        .values(**values)
                        .on_conflict_do_update(
                            index_elements=[GeoGazetteer.name],
                            set=values,
                        )
                    )
                else:
                    await db.execute(pg_insert(GeoGazetteer).values(**values))
                inserted += 1
            await db.commit()
    finally:
        await engine.dispose()
    logger.info("gazetteer seeded inserted=%d kept=%d", inserted, kept)
    print(f"gazetteer: {inserted} written, {kept} already correct")
    return inserted


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    return asyncio.run(run(force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
