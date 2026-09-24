"""Fail-closed installation revision validation and lifecycle transitions.

Composition root of the installation service: ``InstallationService`` binds a
db session, the installation repository, and the capability registry, and
receives its three change reasons via mixins:

- ``validation.ValidationMixin`` — revision CRUD, the fail-closed validation
  battery, and evidence-currency checks.
- ``lifecycle.LifecycleMixin`` — the authority-locked transitions and the
  cache-first runtime authority resolution (the per-turn hot path).
- ``projection.ProjectionMixin`` — the runtime/admin projections and the
  readiness derivation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.registry import CapabilityRegistry, get_capability_registry
from app.models.installation import InstallationManifestRevision
from app.shared.domain.errors import InstallationError
from app.services.installation.authority import RuntimeAuthorityFingerprint
from app.services.installation.lifecycle import LifecycleMixin
from app.services.installation.projection import ProjectionMixin
from app.services.installation.repository import InstallationRepository
from app.services.installation.validation import VALIDATOR_VERSION, ValidationMixin

logger = logging.getLogger(__name__)

__all__ = ["ActiveInstallation", "InstallationService", "VALIDATOR_VERSION"]


@dataclass(frozen=True, slots=True)
class ActiveInstallation:
    revision: InstallationManifestRevision
    fingerprint: RuntimeAuthorityFingerprint


class InstallationService(
    ValidationMixin,
    LifecycleMixin,
    ProjectionMixin,
):
    def __init__(
        self,
        db: AsyncSession,
        *,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        self.db = db
        self.repo = InstallationRepository(db)
        self.registry = registry or get_capability_registry()

    async def _revision_or_error(
        self, revision_id: uuid.UUID, lifecycle: str
    ) -> InstallationManifestRevision:
        revision = await self.repo.get_revision(revision_id)
        if revision is None:
            raise self._error(
                "Installation revision not found",
                "INSTALLATION_REVISION_NOT_FOUND",
                lifecycle,
                status_code=404,
            )
        return revision

    @staticmethod
    def _error(
        message: str,
        code: str,
        lifecycle: str,
        *,
        status_code: int = 409,
        issues: list[dict[str, str | None]] | None = None,
    ) -> InstallationError:
        return InstallationError(
            message,
            code=code,
            lifecycle=lifecycle,
            status_code=status_code,
            issues=issues,
        )
