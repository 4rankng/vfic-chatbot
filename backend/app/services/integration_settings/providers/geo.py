"""Geocoder provider group: the Google Maps credential the distance feature
uses before the free Nominatim fallback.

Google resolves Vietnamese landmarks the OSM data misses (the 2026-10-02
incident: Nominatim put "Núi Đèo" ~120 km from Hải Phòng). It is optional:
without a key the geocoder behaves exactly as before (Nominatim only). The
env value seeds the default; the settings page overrides it per installation.

Map4D was evaluated first (a Vietnamese provider with local landmark data) but
its API proved unreachable from the prod host (connection timeout, 02 Oct), so
it was removed rather than shipped as a dead first hop.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.audit_service import record_audit
from app.services.integration_settings._shared import _secret_status

GOOGLE_MAPS_API_KEY = "google_maps_api_key"

GEO_SETTING_KEYS = (GOOGLE_MAPS_API_KEY,)
GEO_SECRET_KEYS = (GOOGLE_MAPS_API_KEY,)


@dataclass(frozen=True)
class GeoRuntimeConfig:
    """Resolved geocoder credential: the stored value wins over the env default."""

    google_maps_api_key: str = ""


class GeoSettingsMixin:
    """Resolve / admin-view / persist the geocoder credential."""

    async def resolve_geocoder(self) -> GeoRuntimeConfig:
        stored = await self._stored_values(GEO_SETTING_KEYS)
        return GeoRuntimeConfig(
            google_maps_api_key=(
                stored.get(GOOGLE_MAPS_API_KEY) or self.settings.google_maps_api_key
            ),
        )

    async def admin_geocoder_view(self) -> dict:
        cfg = await self.resolve_geocoder()
        return {
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
