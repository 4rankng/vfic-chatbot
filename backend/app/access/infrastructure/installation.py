"""Infrastructure adapters for installation access policies."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.application.installation_access import InstallationAccessPolicy
from app.services.installation.service import ActiveInstallation, InstallationService


class InstallationServiceAuthority:
    def __init__(self, db: AsyncSession) -> None:
        self._service = InstallationService(db)

    async def require_active(self) -> ActiveInstallation:
        return await self._service.require_active()

    async def resolve_active(self) -> ActiveInstallation | None:
        return await self._service.resolve_active()

    async def has_installation_state(self) -> bool:
        return await self._service.repo.get_state() is not None


def build_installation_access_policy(
    db: AsyncSession,
) -> InstallationAccessPolicy[ActiveInstallation]:
    return InstallationAccessPolicy(InstallationServiceAuthority(db))
