"""Application service for single-installation access policies."""

from __future__ import annotations

from typing import Generic

from app.access.application.ports import ActiveInstallationT, InstallationAuthority
from app.access.domain.errors import ResourceNotFoundError


class InstallationAccessPolicy(Generic[ActiveInstallationT]):
    def __init__(self, authority: InstallationAuthority[ActiveInstallationT]) -> None:
        self._authority = authority

    async def require_active(self) -> ActiveInstallationT:
        return await self._authority.require_active()

    async def require_capability(self, capability_id: str) -> ActiveInstallationT:
        active = await self.require_active()
        if capability_id not in active.revision.capability_ids:
            raise ResourceNotFoundError("not found")
        return active

    async def require_capability_or_legacy(
        self, capability_id: str
    ) -> ActiveInstallationT | None:
        active = await self._authority.resolve_active()
        if active is None:
            if not await self._authority.has_installation_state():
                return None
            raise ResourceNotFoundError("not found")
        if capability_id not in active.revision.capability_ids:
            raise ResourceNotFoundError("not found")
        return active
