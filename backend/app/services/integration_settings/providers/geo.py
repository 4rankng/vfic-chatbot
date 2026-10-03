"""Geocoder provider group: the keyed geocoder credentials the distance feature
tries, in order.

Google is the first hop and the only reverse-verification source; Vietmap is the
second and the only provider that takes a region bias. There is no keyless
provider — Nominatim was removed on 2026-10-03 because its relaxation ladder
answered a factory address with the city centroid, and its 1 req/s policy turned
a free fallback into a latency floor. Both hops are optional: with neither key
the catalog reports no distance rather than a guessed one. The env value seeds
the default for each; the settings page overrides them per installation.

Map4D was evaluated first (a Vietnamese provider with local landmark data) but
its API proved unreachable from the prod host (connection timeout, 02 Oct), so
it was removed rather than shipped as a dead first hop.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.audit_service import record_audit
from app.services.integration_settings._shared import _secret_status

VIETMAP_API_KEY = "vietmap_api_key"
GOOGLE_MAPS_API_KEY = "google_maps_api_key"

GEO_SETTING_KEYS = (VIETMAP_API_KEY, GOOGLE_MAPS_API_KEY)
GEO_SECRET_KEYS = (VIETMAP_API_KEY, GOOGLE_MAPS_API_KEY)


@dataclass(frozen=True)
class GeoRuntimeConfig:
    """Resolved geocoder credentials: the stored value wins over the env default."""

    vietmap_api_key: str = ""
    google_maps_api_key: str = ""


class GeoSettingsMixin:
    """Resolve / admin-view / persist the geocoder credentials."""

    async def resolve_geocoder(self) -> GeoRuntimeConfig:
        stored = await self._stored_values(GEO_SETTING_KEYS)
        return GeoRuntimeConfig(
            vietmap_api_key=(
                stored.get(VIETMAP_API_KEY) or self.settings.vietmap_api_key
            ),
            google_maps_api_key=(
                stored.get(GOOGLE_MAPS_API_KEY) or self.settings.google_maps_api_key
            ),
        )

    async def admin_geocoder_view(self) -> dict:
        cfg = await self.resolve_geocoder()
        return {
            "vietmap_api_key": _secret_status(cfg.vietmap_api_key),
            "google_maps_api_key": _secret_status(cfg.google_maps_api_key),
        }

    async def update_geocoder(
        self,
        values: dict[str, str | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in GEO_SETTING_KEYS or value is None:
                continue
            if await self._write_setting(
                key,
                str(value),
                actor_id=actor_id,
                is_secret=key in GEO_SECRET_KEYS,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_geocoder_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="geocoder",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
        return changed
