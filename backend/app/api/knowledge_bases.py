"""Admin API for standalone, shareable knowledge bases."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_admin
from app.core.db import get_db
from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeDocument
from app.models.persona import Persona
from app.models.user import User
from app.schemas.knowledge_bases import (
    DirectContextCapacityOut,
    DirectContextFileDetailOut,
    DirectContextFileOut,
    DirectContextFileUpsert,
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseOut,
    KnowledgeBaseProjectFactoryOut,
    KnowledgeBaseProjectOut,
    KnowledgeBaseUpdate,
    LegacyKnowledgeBootstrap,
)
from app.services.knowledge_base_capacity import direct_context_capacity
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.project.service import ProjectService


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


async def _serialize(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    attached_agent_count: int | None = None,
    project_count: int | None = None,
    direct_file: KnowledgeBaseDirectFile | None = None,
    direct_file_loaded: bool = False,
) -> KnowledgeBaseOut:
    if attached_agent_count is None:
        attached_agent_count = await db.scalar(
            select(func.count(Persona.id)).where(Persona.knowledge_base_id == knowledge_base.id)
        )
    if project_count is None:
        project_count = await db.scalar(
            select(func.count(Project.id)).where(Project.knowledge_base_id == knowledge_base.id)
        )
    if not direct_file_loaded:
        direct_file = await db.scalar(
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


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> KnowledgeBaseListResponse:
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
        await db.execute(
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
    return KnowledgeBaseListResponse(
        data=[
            await _serialize(
                db,
                knowledge_base,
                attached_agent_count=int(agent_count or 0),
                project_count=int(project_count or 0),
                direct_file=direct_file,
                direct_file_loaded=True,
            )
            for knowledge_base, agent_count, project_count, direct_file in rows
        ],
        total=len(rows),
    )


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseOut:
    knowledge_base = await KnowledgeBaseService(db).create(body, admin)
    return await _serialize(db, knowledge_base)


@router.post("/bootstrap-legacy", response_model=KnowledgeBaseOut)
async def bootstrap_legacy_knowledge_base(
    body: LegacyKnowledgeBootstrap,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseOut:
    knowledge_base = await KnowledgeBaseService(db).bootstrap_legacy(body, admin)
    return await _serialize(db, knowledge_base)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseOut:
    knowledge_base = await KnowledgeBaseService(db).get(knowledge_base_id)
    return await _serialize(db, knowledge_base)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseOut:
    knowledge_base = await KnowledgeBaseService(db).update(knowledge_base_id, body, admin)
    return await _serialize(db, knowledge_base)


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    knowledge_base_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await KnowledgeBaseService(db).delete(knowledge_base_id, admin)


@router.get("/{knowledge_base_id}/projects", response_model=list[KnowledgeBaseProjectOut])
async def list_knowledge_base_projects(
    knowledge_base_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeBaseProjectOut]:
    await KnowledgeBaseService(db).get(knowledge_base_id)
    projects = list(
        (
            await db.scalars(
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
        await db.execute(
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
        await db.execute(
            select(KnowledgeDocument.project_id, func.count(KnowledgeDocument.id))
            .where(KnowledgeDocument.project_id.in_(project_ids))
            .group_by(KnowledgeDocument.project_id)
        )
    ).all()
    document_counts = {project_id: int(count) for project_id, count in document_rows}

    job_rows = (
        await db.execute(
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
            factories=factories[project.id],
        )
        for project in projects
    ]


@router.post("/{knowledge_base_id}/projects/{project_id}", response_model=KnowledgeBaseProjectOut)
async def attach_project_to_knowledge_base(
    knowledge_base_id: uuid.UUID,
    project_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseProjectOut:
    project = await KnowledgeBaseService(db).attach_project(knowledge_base_id, project_id, admin)
    return KnowledgeBaseProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        is_active=project.is_active,
        knowledge_document_count=0,
        active_job_count=0,
    )


@router.put("/{knowledge_base_id}/direct-file", response_model=DirectContextFileOut)
async def upsert_direct_context_file(
    knowledge_base_id: uuid.UUID,
    body: DirectContextFileUpsert,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DirectContextFileOut:
    project_id = await db.scalar(
        select(Project.id).where(Project.knowledge_base_id == knowledge_base_id)
    )
    if project_id is not None:
        direct_file = await ProjectService(db).replace_single_page(project_id, body, admin)
    else:
        direct_file = await KnowledgeBaseService(db).upsert_direct_file(
            knowledge_base_id, body, admin
        )
    return DirectContextFileOut.model_validate(direct_file)


@router.get("/{knowledge_base_id}/direct-file", response_model=DirectContextFileDetailOut)
async def get_direct_context_file(
    knowledge_base_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DirectContextFileDetailOut:
    knowledge_base = await KnowledgeBaseService(db).get(knowledge_base_id)
    direct_file = await db.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    if direct_file is None:
        from app.services.errors import ConflictError

        raise ConflictError("A direct-context knowledge base needs one text file before use")
    return DirectContextFileDetailOut(
        **DirectContextFileOut.model_validate(direct_file).model_dump(),
        text=direct_file.raw_text,
    )


@router.get(
    "/{knowledge_base_id}/direct-context-capacity",
    response_model=DirectContextCapacityOut,
)
async def get_direct_context_capacity(
    knowledge_base_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DirectContextCapacityOut:
    knowledge_base = await KnowledgeBaseService(db).get(knowledge_base_id)
    direct_file = await db.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    if direct_file is None:
        from app.services.errors import ConflictError

        raise ConflictError("A direct-context knowledge base needs one text file before use")
    capacity = await direct_context_capacity(db, direct_file)
    return DirectContextCapacityOut(
        provider=capacity.provider,
        model=capacity.model,
        context_window_tokens=capacity.context_window_tokens,
        reserved_tokens=capacity.reserved_tokens,
        estimated_input_tokens=capacity.estimated_input_tokens,
        available_input_tokens=capacity.available_input_tokens,
        fits=capacity.fits,
    )
