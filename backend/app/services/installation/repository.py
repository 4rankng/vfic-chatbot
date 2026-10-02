"""Database access for the immutable installation lifecycle."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.conversation import Conversation
from app.models.ingestion_template import IngestionTemplateVersion, TemplateVersionStatus
from app.models.installation import (
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationState,
)
from app.models.integration import IntegrationSetting
from app.models.job import Job
from app.models.knowledge import KnowledgeCategory, KnowledgeCategoryRevision
from app.models.lead import Lead
from app.models.persona import Persona, PersonaVersion
from app.services.installation.catalog import (
    INTEGRATION_REFERENCE_ENABLE_KEYS,
    INTEGRATION_REFERENCE_REQUIREMENTS,
)
from app.services.integration_settings import IntegrationSettingsCipher


INSTALLATION_AUTHORITY_LOCK = 7_423_811_609


class InstallationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def acquire_authority_lock(self) -> None:
        await self.db.execute(select(func.pg_advisory_xact_lock(INSTALLATION_AUTHORITY_LOCK)))

    async def acquire_runtime_dispatch_lock(self) -> None:
        """Hold a shared authority lock until a runtime-bound send is finalized."""
        await self.db.execute(select(func.pg_advisory_xact_lock_shared(INSTALLATION_AUTHORITY_LOCK)))

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
                IngestionTemplateVersion.id.in_(version_ids),
                IngestionTemplateVersion.status == TemplateVersionStatus.PUBLISHED,
            )
        )
        return {str(version_id): checksum for version_id, checksum in rows.all()}

    async def configured_integrations(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        required_setting_keys = {
            setting_key
            for reference in keys
            for setting_key in INTEGRATION_REFERENCE_REQUIREMENTS.get(reference, ())
        }
        settings = list(
            (
                await self.db.scalars(
                    select(IntegrationSetting).where(
                        IntegrationSetting.key.in_(required_setting_keys)
                    )
                )
            ).all()
        )
        cipher = IntegrationSettingsCipher()
        values: dict[str, str] = {}
        for setting in settings:
            try:
                values[setting.key] = cipher.decrypt(setting.encrypted_value).strip()
            except Exception:  # noqa: BLE001 - invalid ciphertext is not configured authority
                continue
        return {
            reference
            for reference in keys
            if reference in INTEGRATION_REFERENCE_REQUIREMENTS
            and all(values.get(key) for key in INTEGRATION_REFERENCE_REQUIREMENTS[reference])
            and (
                reference not in INTEGRATION_REFERENCE_ENABLE_KEYS
                or values[INTEGRATION_REFERENCE_ENABLE_KEYS[reference]].lower()
                in {"1", "true", "yes", "on"}
            )
        }

    async def integration_keys(self) -> list[str]:
        return list(
            (
                await self.db.scalars(
                    select(IntegrationSetting.key).order_by(IntegrationSetting.key.asc())
                )
            ).all()
        )

    async def active_kb_vector(self) -> tuple[tuple[str, str], ...]:
        """(project_slug, knowledge checksum) for the installation manifest.

        Derived from the ACTIVE category revisions — the category lane owns
        knowledge now (the legacy KB-version release manifests are gone).
        A project with categories but an unpinned active revision fails
        loudly, so the manifest can never ship an unchecksummed knowledge
        state.
        """
        rows = await self.db.execute(
            select(
                Project.slug,
                KnowledgeCategory.category_key,
                KnowledgeCategoryRevision.content_sha256,
            )
            .join(KnowledgeCategory, KnowledgeCategory.project_id == Project.id)
            .join(
                KnowledgeCategoryRevision,
                KnowledgeCategoryRevision.id == KnowledgeCategory.active_revision_id,
            )
            .where(Project.is_active.is_(True))
            .order_by(Project.slug, KnowledgeCategory.category_key)
        )
        grouped: dict[str, list[str]] = {}
        for slug, category_key, checksum in rows.all():
            if not checksum:
                raise ValueError(
                    f"active category revision is not checksum-pinned: {slug}/{category_key}"
                )
            grouped.setdefault(slug, []).append(checksum)
        vector = [
            (slug, hashlib.sha256(",".join(checksums).encode()).hexdigest())
            for slug, checksums in grouped.items()
        ]
        return tuple(sorted(vector))

    async def operational_data_kinds(self) -> set[str]:
        for model in (Job, Lead, Conversation):
            if await self.db.scalar(select(func.count()).select_from(model)):
                return {"recruitment"}
        return set()

    async def has_legacy_workspace(self) -> bool:
        """Recognize an established pre-installation recruitment workspace.

        The setup lifecycle was added after the original single-tenant CRM. A
        fresh deployment has none of these records; an existing workspace has
        a configured project, persona, integration settings, and history.
        """
        for model in (Project, Persona, IntegrationSetting, Conversation):
            if not await self.db.scalar(select(func.count()).select_from(model)):
                return False
        return True

    async def lock_operational_writers(self) -> None:
        """Close the first-activation count/commit window against recruitment writers."""
        await self.db.execute(text("LOCK TABLE jobs, leads, conversations IN SHARE MODE"))
