"""TingTing provider group: the password-reset API key.

One admin field, no per-tenant content: the workflow guide is embedded in
:mod:`app.graph.tingting_guide` and the origin is a validated constant
(:data:`app.services.tingting_api.TINGTING_API_BASE_DEFAULT`). The mixin is a
thin delegate so the settings service exposes one uniform surface per group.
"""

from __future__ import annotations


class TingtingSettingsMixin:
    """Resolve/admin/persist for the deployment-wide TingTing integration."""

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
        return await self._tingting_service().admin_view()

    async def update_tingting(
        self, values: dict[str, str | None], *, actor_id
    ) -> dict:
        """Persist ``api_key`` / ``reset_oa_id`` (tri-state: absent keeps, ``""`` clears)."""
        service = self._tingting_service()
        if "api_key" in values:
            await service.replace_key(values.get("api_key"), actor_id=actor_id)
        if "reset_oa_id" in values:
            await service.replace_reset_oa_id(values.get("reset_oa_id"), actor_id=actor_id)
        return await service.admin_view()


__all__ = ["TingtingSettingsMixin"]
