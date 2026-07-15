"""Database access for the immutable installation lifecycle."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.conversation import Conversation
from app.models.ingestion_template import IngestionTemplateVersion
from app.models.installation import (
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationState,
)
from app.models.integration import IntegrationSetting
from app.models.job import Job
from app.models.knowledge import KBVersion
from app.models.lead import Lead
from app.models.persona import PersonaVersion


INSTALLATION_AUTHORITY_LOCK = 7_423_811_609


class InstallationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def acquire_authority_lock(self) -> None:
        await self.db.execute(select(func.pg_advisory_xact_lock(INSTALLATION_AUTHORITY_LOCK)))

    async def get_state(self, *, for_update: bool = False) -> InstallationState | None:
        statement = select(InstallationState).where(InstallationState.singleton_id == 1)
        if for_update:
            statement = statement.with_for_update()
        return (await self.db.scalars(statement)).one_or_none()

    async def advance_generation_for_active_authority_change(self) -> bool:
        """Fence work when a non-manifest authority pointer changes in this transaction."""
        state = await self.get_state(for_update=True)
        if state is None or state.active_revision_id is None:
            return False
        state.authority_generation += 1
        state.lock_version += 1
        state.updated_at = func.now()
        return True

    async def get_revision(self, revision_id: uuid.UUID) -> InstallationManifestRevision | None:
        return await self.db.get(InstallationManifestRevision, revision_id)

    async def get_persona_version(self, version_id: uuid.UUID) -> PersonaVersion | None:
        return await self.db.get(PersonaVersion, version_id)

    async def get_valid_validations(
        self, revision_id: uuid.UUID, *, limit: int = 100
    ) -> list[InstallationManifestValidation]:
        statement = (
            select(InstallationManifestValidation)
            .where(
                InstallationManifestValidation.revision_id == revision_id,
                InstallationManifestValidation.is_valid.is_(True),
            )
            .order_by(
                InstallationManifestValidation.created_at.desc(),
                InstallationManifestValidation.id.desc(),
            )
            .limit(limit)
        )
        return list((await self.db.scalars(statement)).all())

    async def template_checksums(self, version_ids: list[uuid.UUID]) -> dict[str, str | None]:
        if not version_ids:
            return {}
        rows = await self.db.execute(
            select(IngestionTemplateVersion.id, IngestionTemplateVersion.checksum).where(
                IngestionTemplateVersion.id.in_(version_ids)
            )
        )
        return {str(version_id): checksum for version_id, checksum in rows.all()}

    async def configured_integrations(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        return set(
            (
                await self.db.scalars(
                    select(IntegrationSetting.key).where(IntegrationSetting.key.in_(keys))
                )
            ).all()
        )

    async def active_kb_vector(self) -> tuple[tuple[str, str], ...]:
        rows = await self.db.execute(
            select(Project.slug, KBVersion.id, KBVersion.release_manifest_sha256)
            .join(KBVersion, Project.active_kb_version_id == KBVersion.id)
            .where(Project.is_active.is_(True))
        )
        vector: list[tuple[str, str]] = []
        for slug, version_id, checksum in rows.all():
            if checksum is None:
                raise ValueError(f"active KB version is not checksum-pinned: {slug}/{version_id}")
            vector.append((slug, checksum))
        return tuple(sorted(vector))

    async def operational_data_kinds(self) -> set[str]:
        for model in (Job, Lead, Conversation):
            if await self.db.scalar(select(func.count()).select_from(model)):
                return {"recruitment"}
        return set()

    async def lock_operational_writers(self) -> None:
        """Close the first-activation count/commit window against recruitment writers."""
        await self.db.execute(text("LOCK TABLE jobs, leads, conversations IN SHARE MODE"))
