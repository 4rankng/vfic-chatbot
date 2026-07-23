"""Admin API for standalone, shareable knowledge bases."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_admin
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db
from app.schemas.knowledge_bases import (
    DirectContextCapacityOut,
    DirectContextFileDetailOut,
    DirectContextFileOut,
    DirectContextFileUpsert,
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseOut,
    KnowledgeBaseProjectOut,
    KnowledgeBaseUpdate,
    LegacyKnowledgeBootstrap,
)
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.project.service import ProjectService


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeBaseListResponse:
    rows = await KnowledgeBaseService(db).list_detailed()
    return KnowledgeBaseListResponse(
        data=rows,
        total=len(rows),
    )


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    body: KnowledgeBaseCreate,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeBaseOut:
    service = KnowledgeBaseService(db)
    knowledge_base = await service.create(body, admin)
    return await service.describe(knowledge_base)


@router.post("/bootstrap-legacy", response_model=KnowledgeBaseOut)
async def bootstrap_legacy_knowledge_base(
    body: LegacyKnowledgeBootstrap,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeBaseOut:
    service = KnowledgeBaseService(db)
    knowledge_base = await service.bootstrap_legacy(body, admin)
    return await service.describe(knowledge_base)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeBaseOut:
    service = KnowledgeBaseService(db)
    knowledge_base = await service.get(knowledge_base_id)
    return await service.describe(knowledge_base)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> KnowledgeBaseOut:
    service = KnowledgeBaseService(db)
    knowledge_base = await service.update(knowledge_base_id, body, admin)
    return await service.describe(knowledge_base)


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    knowledge_base_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> None:
    await KnowledgeBaseService(db).delete(knowledge_base_id, admin)


@router.get("/{knowledge_base_id}/projects", response_model=list[KnowledgeBaseProjectOut])
async def list_knowledge_base_projects(
    knowledge_base_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> list[KnowledgeBaseProjectOut]:
    return await KnowledgeBaseService(db).list_projects(knowledge_base_id)


@router.post("/{knowledge_base_id}/projects/{project_id}", response_model=KnowledgeBaseProjectOut)
async def attach_project_to_knowledge_base(
    knowledge_base_id: uuid.UUID,
    project_id: uuid.UUID,
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
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
    admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> DirectContextFileOut:
    project_id = await KnowledgeBaseService(db).find_owner_project_id(knowledge_base_id)
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
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> DirectContextFileDetailOut:
    return await KnowledgeBaseService(db).get_direct_file_detail(knowledge_base_id)


@router.get(
    "/{knowledge_base_id}/direct-context-capacity",
    response_model=DirectContextCapacityOut,
)
async def get_direct_context_capacity(
    knowledge_base_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> DirectContextCapacityOut:
    return await KnowledgeBaseService(db).get_direct_context_capacity_out(knowledge_base_id)
