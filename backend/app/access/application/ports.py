"""Framework-free ports for access policies."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar


class RoleCarrier(Protocol):
    role: object


PrincipalT = TypeVar("PrincipalT", bound=RoleCarrier)


class CapabilityRevision(Protocol):
    capability_ids: Sequence[str]


class ActiveInstallationRecord(Protocol):
    revision: CapabilityRevision


ActiveInstallationT = TypeVar("ActiveInstallationT", bound=ActiveInstallationRecord)


class InstallationAuthority(Protocol[ActiveInstallationT]):
    async def require_active(self) -> ActiveInstallationT:
        """Load the active installation or fail."""

    async def resolve_active(self) -> ActiveInstallationT | None:
        """Resolve the active installation when present."""

    async def has_installation_state(self) -> bool:
        """Return whether installation adoption has occurred."""
