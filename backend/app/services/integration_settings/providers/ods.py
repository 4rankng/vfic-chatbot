"""ODS provider group: the daily voice-transcript insights configuration.

ODS is the vendor label for the CloudFone-hosted call-center integration (the
underlying API stays api.cloudfone.vn). Admin-editable from the settings
console: the CloudFone API key (encrypted at rest, no env fallback — the key is
deployment-specific and only admins hold it), the recipient list for the daily
insights email, and the on/off switch. There is no worker-owned state row: the
tick always reports on the previous full day, so re-running it is idempotent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from app.services.audit_service import record_audit
from app.services.integration_settings._shared import _secret_status
from app.services.integration_settings.providers.email_digest import (
    parse_recipients,
)
from app.shared.domain.errors import ValidationError

logger = logging.getLogger(__name__)

ODS_API_KEY = "ods_api_key"
ODS_RECIPIENTS = "ods_recipients"
# Admin on/off switch for the daily insights send ("1"/"0"; unset = off).
ODS_ENABLED = "ods_enabled"

ODS_SETTING_KEYS = (ODS_API_KEY, ODS_RECIPIENTS, ODS_ENABLED)

# The admin API speaks OdsIntegrationSettingsUpdate schema names; the KV table
# keeps the namespaced keys. One explicit map joins the two — and doubles as
# the request whitelist (a PUT can never write an arbitrary integration row).
API_FIELD_TO_SETTING_KEY = {
    "api_key": ODS_API_KEY,
    "recipients": ODS_RECIPIENTS,
    "enabled": ODS_ENABLED,
}


@dataclass(frozen=True)
class OdsRuntimeConfig:
    api_key: str = ""
    recipients: tuple[str, ...] = ()
    enabled: bool = False


class OdsSettingsMixin:
    """Resolve/admin/persist for the ODS (CloudFone) insights integration."""

    if TYPE_CHECKING:
        # Supplied by IntegrationSettingsService, the class that mixes these in.
        # Declarations only: TYPE_CHECKING is False at runtime, so nothing here is
        # ever assigned and the composed class stays the single source of truth.
        db: AsyncSession
        settings: Settings
        cipher: IntegrationSettingsCipher

        from collections.abc import Iterable

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.config import Settings
        from app.services.integration_settings.cipher import IntegrationSettingsCipher

        async def _stored_values(self, keys: Iterable[str]) -> dict[str, str]: ...

        async def _write_setting(
            self,
            key: str,
            value: str,
            *,
            actor_id: object | None = None,
            is_secret: bool,
        ) -> bool: ...

    async def resolve_ods(self) -> OdsRuntimeConfig:
        """Stored-only resolution: no env fallback exists for this vendor key."""
        stored = await self._stored_values(ODS_SETTING_KEYS)
        raw_enabled = (stored.get(ODS_ENABLED) or "").strip()
        return OdsRuntimeConfig(
            api_key=stored.get(ODS_API_KEY) or "",
            recipients=tuple(parse_recipients(stored.get(ODS_RECIPIENTS))),
            # Unset row = off: this integration is opt-in, unlike the digest
            # whose owner wanted the daily send running out of the box.
            enabled=raw_enabled in {"1", "true", "yes", "on"},
        )

    async def admin_ods_view(self) -> dict:
        cfg = await self.resolve_ods()
        return {
            "api_key": _secret_status(cfg.api_key),
            "recipients": list(cfg.recipients),
            # Effective state: the admin toggle AND somewhere to send to AND a
            # key to fetch with — a toggle-on without either can't deliver, so
            # the view reports off and the status line explains why.
            "enabled": cfg.enabled and bool(cfg.api_key) and bool(cfg.recipients),
        }

    async def update_ods(self, values: dict[str, object], *, actor_id) -> dict:
        """Validate + persist the admin-editable ODS fields; returns the view.

        ``values`` uses the API field names (``api_key``, ``recipients``,
        ``enabled``) — the names the settings page sends. Anything outside
        ``API_FIELD_TO_SETTING_KEY`` is rejected, so a typo cannot write an
        arbitrary integration row.
        """
        unknown = set(values) - set(API_FIELD_TO_SETTING_KEY)
        if unknown:
            raise ValidationError(f"Trường không hợp lệ: {', '.join(sorted(unknown))}")

        changed: list[str] = []

        raw_api_key = values.get("api_key")
        if raw_api_key is not None and str(raw_api_key).strip():
            await self._write_setting(
                ODS_API_KEY,
                str(raw_api_key),
                actor_id=actor_id,
                is_secret=True,
            )
            changed.append(ODS_API_KEY)

        if "recipients" in values:
            recipients = parse_recipients(
                cast("str | list[str] | None", values.get("recipients"))
            )
            await self._write_setting(
                ODS_RECIPIENTS,
                ",".join(recipients),
                actor_id=actor_id,
                is_secret=False,
            )
            changed.append(ODS_RECIPIENTS)

        if "enabled" in values:
            enabled = bool(values.get("enabled"))
            await self._write_setting(
                ODS_ENABLED,
                "1" if enabled else "0",
                actor_id=actor_id,
                is_secret=False,
            )
            changed.append(ODS_ENABLED)

        if changed:
            await record_audit(
                self.db,
                action="update_ods_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="ods",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
        return await self.admin_ods_view()
