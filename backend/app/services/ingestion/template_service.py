"""Admin lifecycle for safe template definitions and project assignments."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion_template import (
    IngestionTemplate,
    IngestionTemplateAssignment,
    IngestionTemplateVersion,
    TemplateVersionStatus,
)
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.errors import NotFoundError
from app.services.ingestion.template_compiler import (
    BUILTIN_RECRUITMENT_DEFINITION,
    COMPILER_VERSION,
    compile_template,
)


class TemplateConflictError(ValueError):
    pass


class TemplateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_templates(self) -> list[IngestionTemplate]:
        return list((await self.db.scalars(select(IngestionTemplate).order_by(IngestionTemplate.created_at))).all())

    async def get_template(self, template_id: uuid.UUID) -> IngestionTemplate:
        template = await self.db.get(IngestionTemplate, template_id)
        if template is None:
            raise NotFoundError("ingestion template not found")
        return template

    async def get_version(self, version_id: uuid.UUID) -> IngestionTemplateVersion:
        version = await self.db.get(IngestionTemplateVersion, version_id)
        if version is None:
            raise NotFoundError("ingestion template version not found")
        return version

    async def list_versions(self, template_id: uuid.UUID) -> list[IngestionTemplateVersion]:
        await self.get_template(template_id)
        return list((await self.db.scalars(select(IngestionTemplateVersion).where(IngestionTemplateVersion.template_id == template_id).order_by(IngestionTemplateVersion.version_no.desc()))).all())

    async def create_template(
        self, *, template_key: str, name: str, vertical: str, definition: dict, actor: User
    ) -> tuple[IngestionTemplate, IngestionTemplateVersion]:
        compile_template(definition)
        exists = await self.db.scalar(select(IngestionTemplate.id).where(IngestionTemplate.template_key == template_key))
        if exists is not None:
            raise TemplateConflictError("template_key already exists")
        template = IngestionTemplate(template_key=template_key, name=name, vertical=vertical, created_by=actor.id)
        self.db.add(template)
        await self.db.flush()
        version = IngestionTemplateVersion(template_id=template.id, version_no=1, definition=definition, created_by=actor.id)
        self.db.add(version)
        await record_audit(self.db, action="ingestion_template_created", actor_id=actor.id, target_type="ingestion_template", target_id=str(template.id), payload={"template_key": template_key})
        await self.db.commit()
        await self.db.refresh(template)
        await self.db.refresh(version)
        return template, version

    async def update_draft(self, version_id: uuid.UUID, *, definition: dict, revision: int, actor: User) -> IngestionTemplateVersion:
        version = await self.get_version(version_id)
        if version.status != TemplateVersionStatus.DRAFT:
            raise TemplateConflictError("only DRAFT template versions can be edited")
        if version.revision != revision:
            raise TemplateConflictError("stale template revision")
        compile_template(definition)
        version.definition = definition
        version.revision += 1
        version.updated_at = datetime.now(UTC)
        await record_audit(self.db, action="ingestion_template_draft_updated", actor_id=actor.id, target_type="ingestion_template_version", target_id=str(version.id), payload={"revision": version.revision})
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def publish(self, version_id: uuid.UUID, *, actor: User) -> IngestionTemplateVersion:
        version = await self.get_version(version_id)
        if version.status != TemplateVersionStatus.DRAFT:
            raise TemplateConflictError("only DRAFT template versions can be published")
        artifact, checksum = compile_template(version.definition)
        version.compiled_artifact = artifact
        version.checksum = checksum
        version.compiler_version = COMPILER_VERSION
        version.status = TemplateVersionStatus.PUBLISHED
        version.published_at = datetime.now(UTC)
        version.updated_at = version.published_at
        await record_audit(self.db, action="ingestion_template_published", actor_id=actor.id, target_type="ingestion_template_version", target_id=str(version.id), payload={"checksum": checksum, "compiler_version": COMPILER_VERSION})
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def create_draft_from(self, template_id: uuid.UUID, *, actor: User) -> IngestionTemplateVersion:
        versions = await self.list_versions(template_id)
        source = next((item for item in versions if item.status == TemplateVersionStatus.PUBLISHED), None)
        if source is None:
            raise TemplateConflictError("template has no published version to clone")
        version_no = max(item.version_no for item in versions) + 1
        draft = IngestionTemplateVersion(template_id=template_id, version_no=version_no, definition=source.definition, created_by=actor.id)
        self.db.add(draft)
        await record_audit(self.db, action="ingestion_template_draft_created", actor_id=actor.id, target_type="ingestion_template", target_id=str(template_id), payload={"version_no": version_no})
        await self.db.commit()
        await self.db.refresh(draft)
        return draft

    async def assign(self, project_id: uuid.UUID, *, template_version_id: uuid.UUID, revision: int, actor: User) -> IngestionTemplateAssignment:
        version = await self.get_version(template_version_id)
        if version.status != TemplateVersionStatus.PUBLISHED:
            raise TemplateConflictError("only published template versions can be assigned")
        current = await self.current_assignment(project_id)
        expected = (current.revision if current else 0) + 1
        if revision != expected:
            raise TemplateConflictError("stale assignment revision")
        assignment = IngestionTemplateAssignment(project_id=project_id, template_version_id=template_version_id, revision=revision, assigned_by=actor.id, replaces_assignment_id=current.id if current else None)
        self.db.add(assignment)
        await record_audit(self.db, action="ingestion_template_assigned", actor_id=actor.id, target_type="project", target_id=str(project_id), payload={"template_version_id": str(template_version_id), "revision": revision})
        await self.db.commit()
        await self.db.refresh(assignment)
        return assignment

    async def current_assignment(self, project_id: uuid.UUID) -> IngestionTemplateAssignment | None:
        return await self.db.scalar(select(IngestionTemplateAssignment).where(IngestionTemplateAssignment.project_id == project_id).order_by(IngestionTemplateAssignment.revision.desc()).limit(1))

    async def pinned_version_for_project(self, project_id: uuid.UUID) -> IngestionTemplateVersion:
        assignment = await self.current_assignment(project_id)
        if assignment is not None:
            return await self.get_version(assignment.template_version_id)
        return await self.ensure_builtin_recruitment()

    async def ensure_builtin_recruitment(self) -> IngestionTemplateVersion:
        template = await self.db.scalar(select(IngestionTemplate).where(IngestionTemplate.template_key == "recruitment_factory_builtin"))
        if template is None:
            template = IngestionTemplate(template_key="recruitment_factory_builtin", name="Factory recruitment (built-in)", vertical="recruitment")
            self.db.add(template)
            await self.db.flush()
        version = await self.db.scalar(select(IngestionTemplateVersion).where(IngestionTemplateVersion.template_id == template.id, IngestionTemplateVersion.status == TemplateVersionStatus.PUBLISHED).order_by(IngestionTemplateVersion.version_no.desc()).limit(1))
        if version is not None:
            return version
        artifact, checksum = compile_template(BUILTIN_RECRUITMENT_DEFINITION)
        version_no = int(await self.db.scalar(select(func.coalesce(func.max(IngestionTemplateVersion.version_no), 0) + 1).where(IngestionTemplateVersion.template_id == template.id)) or 1)
        version = IngestionTemplateVersion(template_id=template.id, version_no=version_no, status=TemplateVersionStatus.PUBLISHED, definition=BUILTIN_RECRUITMENT_DEFINITION, compiled_artifact=artifact, checksum=checksum, compiler_version=COMPILER_VERSION, published_at=datetime.now(UTC))
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)
        return version

    async def deprecate(self, version_id: uuid.UUID, *, actor: User) -> IngestionTemplateVersion:
        version = await self.get_version(version_id)
        if version.status != TemplateVersionStatus.PUBLISHED:
            raise TemplateConflictError("only PUBLISHED template versions can be deprecated")
        version.status = TemplateVersionStatus.DEPRECATED
        version.updated_at = datetime.now(UTC)
        await record_audit(self.db, action="ingestion_template_deprecated", actor_id=actor.id, target_type="ingestion_template_version", target_id=str(version.id))
        await self.db.commit()
        return version
