"""Standalone knowledge-base lifecycle and legacy bootstrap operations."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.core.preamble_cache import NS_PREAMBLE
from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseDirectFile,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeDocument,
)
from app.models.persona import Persona
from app.models.user import User
from app.schemas.knowledge_bases import (
    DirectContextCapacityOut,
    DirectContextFileDetailOut,
    DirectContextFileOut,
    DirectContextFileUpsert,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseProjectFactoryOut,
    KnowledgeBaseProjectOut,
    KnowledgeBaseUpdate,
    LegacyKnowledgeBootstrap,
)
from app.services.audit_service import record_audit
from app.shared.domain.errors import ConflictError, NotFoundError
from app.services.knowledge.text_ingestion import canonical_kb_text_stats
from app.services.knowledge_base_capacity import direct_context_capacity
from app.services.knowledge_base_capacity import require_direct_context_ready
from app.schemas.knowledge_categories import KnowledgeCategoryKey


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def canonical_direct_file_stats(text: str):
        return canonical_kb_text_stats(text)

    async def describe(
        self,
        knowledge_base: KnowledgeBase,
        *,
        attached_agent_count: int | None = None,
        project_count: int | None = None,
        direct_file: KnowledgeBaseDirectFile | None = None,
        direct_file_loaded: bool = False,
    ) -> KnowledgeBaseOut:
        if attached_agent_count is None:
            attached_agent_count = await self.db.scalar(
                select(func.count(Persona.id)).where(Persona.knowledge_base_id == knowledge_base.id)
            )
        if project_count is None:
            project_count = await self.db.scalar(
                select(func.count(Project.id)).where(Project.knowledge_base_id == knowledge_base.id)
            )
        if not direct_file_loaded:
            direct_file = await self.db.scalar(
                select(KnowledgeBaseDirectFile).where(
                    KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
                )
            )
        out = KnowledgeBaseOut.model_validate(knowledge_base)
        out.attached_agent_count = int(attached_agent_count or 0)
        out.project_count = int(project_count or 0)
        out.direct_file = (
            DirectContextFileOut.model_validate(direct_file) if direct_file is not None else None
        )
        return out

    async def list_detailed(self) -> list[KnowledgeBaseOut]:
        attached_agent_count = (
            select(func.count(Persona.id))
            .where(Persona.knowledge_base_id == KnowledgeBase.id)
            .correlate(KnowledgeBase)
            .scalar_subquery()
        )
        project_count = (
            select(func.count(Project.id))
            .where(Project.knowledge_base_id == KnowledgeBase.id)
            .correlate(KnowledgeBase)
            .scalar_subquery()
        )
        rows = (
            await self.db.execute(
                select(
                    KnowledgeBase,
                    attached_agent_count.label("attached_agent_count"),
                    project_count.label("project_count"),
                    KnowledgeBaseDirectFile,
                )
                .outerjoin(
                    KnowledgeBaseDirectFile,
                    KnowledgeBaseDirectFile.knowledge_base_id == KnowledgeBase.id,
                )
                .order_by(KnowledgeBase.name)
            )
        ).all()
        return [
            await self.describe(
                knowledge_base,
                attached_agent_count=int(agent_count or 0),
                project_count=int(project_count or 0),
                direct_file=direct_file,
                direct_file_loaded=True,
            )
            for knowledge_base, agent_count, project_count, direct_file in rows
        ]

    async def list(self) -> list[KnowledgeBase]:
        return list((await self.db.scalars(select(KnowledgeBase).order_by(KnowledgeBase.name))).all())

    async def get(self, knowledge_base_id: uuid.UUID) -> KnowledgeBase:
        knowledge_base = await self.db.get(KnowledgeBase, knowledge_base_id)
        if knowledge_base is None:
            raise NotFoundError("Knowledge base not found")
        return knowledge_base

    async def create(self, body: KnowledgeBaseCreate, actor: User) -> KnowledgeBase:
        existing = await self.db.scalar(
            select(KnowledgeBase).where(KnowledgeBase.slug == body.slug)
        )
        if existing is not None:
            raise ConflictError("Knowledge base slug already exists")
        knowledge_base = KnowledgeBase(
            name=body.name.strip(),
            slug=body.slug,
            mode=body.mode,
            description=body.description.strip() if body.description else None,
            created_by=actor.id,
        )
        self.db.add(knowledge_base)
        await self.db.flush()
        await record_audit(
            self.db,
            action="create_knowledge_base",
            actor_id=actor.id,
            target_type="knowledge_base",
            target_id=str(knowledge_base.id),
            payload={"mode": knowledge_base.mode.value},
        )
        await self.db.commit()
        await self.db.refresh(knowledge_base)
        return knowledge_base

    async def update(
        self, knowledge_base_id: uuid.UUID, body: KnowledgeBaseUpdate, actor: User
    ) -> KnowledgeBase:
        knowledge_base = await self.get(knowledge_base_id)
        if body.name is not None:
            knowledge_base.name = body.name.strip()
        if "description" in body.model_fields_set:
            knowledge_base.description = body.description.strip() if body.description else None
        knowledge_base.updated_at = func.now()
        await record_audit(
            self.db,
            action="update_knowledge_base",
            actor_id=actor.id,
            target_type="knowledge_base",
            target_id=str(knowledge_base.id),
        )
        await self.db.commit()
        await self.db.refresh(knowledge_base)
        return knowledge_base

    async def delete(self, knowledge_base_id: uuid.UUID, actor: User) -> None:
        knowledge_base = await self.get(knowledge_base_id)
        attached_agents = await self.db.scalar(
            select(func.count(Persona.id)).where(Persona.knowledge_base_id == knowledge_base.id)
        )
        projects = await self.db.scalar(
            select(func.count(Project.id)).where(Project.knowledge_base_id == knowledge_base.id)
        )
        if attached_agents or projects:
            raise ConflictError("Detach all Agents and Projects before deleting this knowledge base")
        await record_audit(
            self.db,
            action="delete_knowledge_base",
            actor_id=actor.id,
            target_type="knowledge_base",
            target_id=str(knowledge_base.id),
        )
        await self.db.delete(knowledge_base)
        await self.db.commit()

    async def attach_project(
        self, knowledge_base_id: uuid.UUID, project_id: uuid.UUID, actor: User
    ) -> Project:
        raise ConflictError(
            "Projects own their knowledge mode; create the Project instead of attaching a shared KB"
        )

    async def find_owner_project_id(self, knowledge_base_id: uuid.UUID) -> uuid.UUID | None:
        return await self.db.scalar(
            select(Project.id).where(Project.knowledge_base_id == knowledge_base_id)
        )

    async def list_projects(self, knowledge_base_id: uuid.UUID) -> list[KnowledgeBaseProjectOut]:
        await self.get(knowledge_base_id)
        projects = list(
            (
                await self.db.scalars(
                    select(Project)
                    .where(Project.knowledge_base_id == knowledge_base_id)
                    .order_by(Project.name)
                )
            ).all()
        )
        project_ids = [project.id for project in projects]
        if not project_ids:
            return []

        factory_rows = (
            await self.db.execute(
                select(Company.project_id, Company.name, Company.aliases)
                .where(Company.project_id.in_(project_ids))
                .order_by(Company.name)
            )
        ).all()
        factories: dict[uuid.UUID, list[KnowledgeBaseProjectFactoryOut]] = defaultdict(list)
        for project_id, name, aliases in factory_rows:
            factories[project_id].append(
                KnowledgeBaseProjectFactoryOut(name=name, aliases=list(aliases or []))
            )

        document_rows = (
            await self.db.execute(
                select(KnowledgeDocument.project_id, func.count(KnowledgeDocument.id))
                .where(KnowledgeDocument.project_id.in_(project_ids))
                .group_by(KnowledgeDocument.project_id)
            )
        ).all()
        document_counts = {project_id: int(count) for project_id, count in document_rows}

        job_rows = (
            await self.db.execute(
                select(Company.project_id, func.count(Job.id))
                .join(Job, Job.company_id == Company.id)
                .join(Project, Project.id == Company.project_id)
                .where(
                    Company.project_id.in_(project_ids),
                    Job.status == JobStatus.ACTIVE,
                    func.coalesce(Job.vacancy_count, 0) > 0,
                    or_(
                        and_(
                            Project.category_authority_started.is_(True),
                            Job.source_category_revision_id.is_not(None),
                        ),
                        and_(
                            Project.category_authority_started.is_(False),
                            Job.source_category_revision_id.is_(None),
                        ),
                    ),
                )
                .group_by(Company.project_id)
            )
        ).all()
        active_job_counts = {project_id: int(count) for project_id, count in job_rows}

        return [
            KnowledgeBaseProjectOut(
                id=project.id,
                slug=project.slug,
                name=project.name,
                is_active=project.is_active,
                knowledge_document_count=document_counts.get(project.id, 0),
                active_job_count=active_job_counts.get(project.id, 0),
                factories=factories.get(project.id, []),
            )
            for project in projects
        ]

    async def get_direct_file_detail(self, knowledge_base_id: uuid.UUID) -> DirectContextFileDetailOut:
        knowledge_base = await self.get(knowledge_base_id)
        direct_file = await self.db.scalar(
            select(KnowledgeBaseDirectFile).where(
                KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
            )
        )
        if direct_file is None:
            raise ConflictError("A direct-context knowledge base needs one text file before use")
        return DirectContextFileDetailOut(
            **DirectContextFileOut.model_validate(direct_file).model_dump(),
            text=direct_file.raw_text,
        )

    async def get_direct_context_capacity_out(
        self, knowledge_base_id: uuid.UUID
    ) -> DirectContextCapacityOut:
        knowledge_base = await self.get(knowledge_base_id)
        direct_file = await self.db.scalar(
            select(KnowledgeBaseDirectFile).where(
                KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
            )
        )
        if direct_file is None:
            raise ConflictError("A direct-context knowledge base needs one text file before use")
        capacity = await direct_context_capacity(self.db, direct_file)
        return DirectContextCapacityOut(
            provider=capacity.provider,
            model=capacity.model,
            context_window_tokens=capacity.context_window_tokens,
            reserved_tokens=capacity.reserved_tokens,
            estimated_input_tokens=capacity.estimated_input_tokens,
            available_input_tokens=capacity.available_input_tokens,
            fits=capacity.fits,
        )

    async def upsert_direct_file(
        self,
        knowledge_base_id: uuid.UUID,
        body: DirectContextFileUpsert,
        actor: User,
        *,
        commit: bool = True,
    ) -> KnowledgeBaseDirectFile:
        knowledge_base = await self.get(knowledge_base_id)
        if knowledge_base.mode is not KnowledgeBaseMode.DIRECT_CONTEXT:
            raise ConflictError("Only direct-context knowledge bases accept a direct text file")
        stats = self.canonical_direct_file_stats(body.text)
        if not stats.normalized_text:
            raise ConflictError("Direct-context knowledge text cannot be empty")
        direct_file = await self.db.scalar(
            select(KnowledgeBaseDirectFile).where(
                KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
            )
        )
        if direct_file is None:
            direct_file = KnowledgeBaseDirectFile(
                knowledge_base_id=knowledge_base.id,
                filename=body.filename,
                raw_text=body.text,
                normalized_text=stats.normalized_text,
                content_sha256=stats.content_sha256,
                char_count=stats.char_count,
                line_count=stats.line_count,
                updated_by=actor.id,
            )
            self.db.add(direct_file)
            action = "create_knowledge_base_direct_file"
        else:
            direct_file.filename = body.filename
            direct_file.raw_text = body.text
            direct_file.normalized_text = stats.normalized_text
            direct_file.content_sha256 = stats.content_sha256
            direct_file.char_count = stats.char_count
            direct_file.line_count = stats.line_count
            direct_file.updated_by = actor.id
            direct_file.updated_at = func.now()
            action = "update_knowledge_base_direct_file"
        await self.db.flush()
        await require_direct_context_ready(self.db, knowledge_base)
        await record_audit(
            self.db,
            action=action,
            actor_id=actor.id,
            target_type="knowledge_base",
            target_id=str(knowledge_base.id),
        )
        if commit:
            await self.db.commit()
            await self.db.refresh(direct_file)
        return direct_file

    async def bootstrap_legacy(
        self, body: LegacyKnowledgeBootstrap, actor: User
    ) -> KnowledgeBase:
        """Idempotently migrate one legacy Project to its owned RAG KB."""
        if len(set(body.project_ids)) != 1:
            raise ConflictError("Legacy migration requires exactly one Project per knowledge base")
        persona = await self.db.get(Persona, body.persona_id)
        if persona is None:
            raise NotFoundError("Agent not found")
        knowledge_base = await self.db.scalar(
            select(KnowledgeBase).where(KnowledgeBase.slug == body.knowledge_base_slug)
        )
        if knowledge_base is None:
            knowledge_base = KnowledgeBase(
                name=body.knowledge_base_name.strip(),
                slug=body.knowledge_base_slug,
                mode=KnowledgeBaseMode.RAG,
                created_by=actor.id,
            )
            self.db.add(knowledge_base)
            await self.db.flush()
        elif knowledge_base.mode is not KnowledgeBaseMode.RAG:
            raise ConflictError("Legacy Projects can only be attached to a RAG knowledge base")

        projects = list(
            (
                await self.db.scalars(select(Project).where(Project.id.in_(body.project_ids)))
            ).all()
        )
        if len(projects) != len(set(body.project_ids)):
            raise NotFoundError("One or more Projects were not found")
        if persona.knowledge_base_id not in (None, knowledge_base.id):
            raise ConflictError("Agent already belongs to another knowledge base")
        for project in projects:
            if project.knowledge_base_id not in (None, knowledge_base.id):
                raise ConflictError("A Project already belongs to another knowledge base")

        project = projects[0]
        if getattr(knowledge_base, "project_id", None) not in (None, project.id):
            raise ConflictError("Knowledge base already belongs to another Project")

        persona.knowledge_base_id = knowledge_base.id
        if body.persona_name is not None:
            persona.name = body.persona_name.strip()
        if body.persona_slug is not None:
            persona.slug = body.persona_slug
        knowledge_base.project_id = project.id
        project.knowledge_base_id = knowledge_base.id
        existing_categories = {
            str(value)
            for value in (
                await self.db.scalars(
                    select(KnowledgeCategory.category_key).where(
                        KnowledgeCategory.project_id == project.id
                    )
                )
            ).all()
        }
        self.db.add_all(
            [
                KnowledgeCategory(project_id=project.id, category_key=key.value)
                for key in KnowledgeCategoryKey
                if key.value not in existing_categories
            ]
        )
        await record_audit(
            self.db,
            action="bootstrap_legacy_knowledge_base",
            actor_id=actor.id,
            target_type="knowledge_base",
            target_id=str(knowledge_base.id),
            payload={
                "persona_id": str(persona.id),
                "project_ids": sorted(str(project.id) for project in projects),
            },
        )
        await self.db.commit()
        # The direct-context routing catalog keys off NS_PREAMBLE; a legacy
        # project attaching to a KB must invalidate it like every project write.
        await bump_cache_version(NS_PREAMBLE)
        await self.db.refresh(knowledge_base)
        return knowledge_base
