"""Standalone knowledge-base lifecycle and legacy bootstrap operations."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
from app.models.persona import Persona
from app.models.user import User
from app.schemas.knowledge_bases import (
    DirectContextFileUpsert,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    LegacyKnowledgeBootstrap,
)
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, NotFoundError
from app.services.knowledge.text_ingestion import kb_text_stats
from app.services.knowledge_base_capacity import require_direct_context_ready


class KnowledgeBaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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
        knowledge_base = await self.get(knowledge_base_id)
        if knowledge_base.mode is not KnowledgeBaseMode.RAG:
            raise ConflictError("Only RAG knowledge bases can contain Projects")
        project = await self.db.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if project.knowledge_base_id not in (None, knowledge_base.id):
            raise ConflictError("Project already belongs to another knowledge base")
        project.knowledge_base_id = knowledge_base.id
        await record_audit(
            self.db,
            action="attach_project_to_knowledge_base",
            actor_id=actor.id,
            target_type="project",
            target_id=str(project.id),
            payload={"knowledge_base_id": str(knowledge_base.id)},
        )
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def upsert_direct_file(
        self,
        knowledge_base_id: uuid.UUID,
        body: DirectContextFileUpsert,
        actor: User,
    ) -> KnowledgeBaseDirectFile:
        knowledge_base = await self.get(knowledge_base_id)
        if knowledge_base.mode is not KnowledgeBaseMode.DIRECT_CONTEXT:
            raise ConflictError("Only direct-context knowledge bases accept a direct text file")
        stats = kb_text_stats(body.text)
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
        await self.db.commit()
        await self.db.refresh(direct_file)
        return direct_file

    async def bootstrap_legacy(
        self, body: LegacyKnowledgeBootstrap, actor: User
    ) -> KnowledgeBase:
        """Idempotently bind an existing Agent and legacy Projects to a RAG KB."""
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

        persona.knowledge_base_id = knowledge_base.id
        if body.persona_name is not None:
            persona.name = body.persona_name.strip()
        if body.persona_slug is not None:
            persona.slug = body.persona_slug
        for project in projects:
            project.knowledge_base_id = knowledge_base.id
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
        await self.db.refresh(knowledge_base)
        return knowledge_base
