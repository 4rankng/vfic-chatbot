"""TingTing provider group: the password-reset API key.

One admin field, no per-tenant content: the workflow guide is embedded in
:mod:`app.graph.tingting_guide` and the origin is a validated constant
(:data:`app.services.tingting_api.TINGTING_API_BASE_DEFAULT`). The mixin is a
thin delegate so the settings service exposes one uniform surface per group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


class TingtingSettingsMixin:
    """Resolve/admin/persist for the deployment-wide TingTing integration."""

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

    def _tingting_service(self):
        # Imported per call: the TingTing service pulls in the project-external-
        # API validators, whose package import chain reaches this module's
        # package, so a module-level import would close a cycle.
        from app.services.tingting_api import TingtingApiService

        return TingtingApiService(self.db, settings=self.settings, cipher=self.cipher)

    async def resolve_tingting(self):
        """The callable runtime (fixed origin + decrypted key), or ``None``."""
        return await self._tingting_service().runtime()

    async def admin_tingting_view(self) -> dict:
        view = await self._tingting_service().admin_view()
        view.update(await self._tingting_oa_link_service().view())
        return view

    def _tingting_oa_link_service(self):
        from app.services.tingting_oa import TingtingOaLinkService

        return TingtingOaLinkService(self.db, settings=self.settings, cipher=self.cipher)

    async def link_tingting_oa(self, values: dict[str, str | None], *, actor_id) -> dict:
        """Store the TingTing OA credentials, probe Zalo, register the account."""
        service = self._tingting_oa_link_service()
        view = await service.link(values, actor_id=actor_id)
        merged = await self._tingting_service().admin_view()
        merged.update(view)
        return merged

    async def update_tingting(
        self, values: dict[str, str | None], *, actor_id
    ) -> dict:
        """Persist the API key, the escalation hotline, and/or the support-OA credentials.

        ``reset_oa_id`` is no longer an admin field — it follows the verified
        link (see :mod:`app.services.tingting_oa`) — but the key stays accepted
        so existing callers and tests keep their meaning.
        """
        service = self._tingting_service()
        if "api_key" in values:
            await service.replace_key(values.get("api_key"), actor_id=actor_id)
        if "reset_oa_id" in values:
            await service.replace_reset_oa_id(values.get("reset_oa_id"), actor_id=actor_id)
        if "hotline" in values:
            await service.replace_hotline(values.get("hotline"), actor_id=actor_id)
        oa_values = {
            base: values[base]
            for base in (
                "zalo_oa_app_id",
                "zalo_oa_secret_key",
                "zalo_oa_access_token",
                "zalo_oa_refresh_token",
            )
            if base in values
        }
        if oa_values:
            link_service = self._tingting_oa_link_service()
            if all(not str(value or "").strip() for value in oa_values.values()):
                # Every field cleared: the operator is removing the OA, so drop
                # the credentials and the binding instead of probing an empty
                # token (which would just report "cần OA Access Token").
                await link_service.unlink(actor_id=actor_id)
            else:
                await link_service.link(oa_values, actor_id=actor_id)
        return await self.admin_tingting_view()


__all__ = ["TingtingSettingsMixin"]
