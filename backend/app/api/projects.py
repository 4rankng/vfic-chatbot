"""Projects ("product catalog") admin API — CRUD + master-index rebuild."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.company import Project
from app.models.user import User
from app.schemas.projects import ProjectCreate, ProjectListResponse, ProjectOut, ProjectUpdate
from app.services.audit_service import record_audit

router = APIRouter(prefix="/knowledge/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    is_active: bool | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    q = select(Project).order_by(Project.created_at.desc())
    if is_active is not None:
        q = q.where(Project.is_active == is_active)
    rows = list((await db.scalars(q)).all())
    return ProjectListResponse(data=[ProjectOut.model_validate(p) for p in rows], total=len(rows))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> ProjectOut:
    proj = Project(slug=body.slug.strip(), name=body.name.strip(), is_active=body.is_active)
    db.add(proj)
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — unique slug violation etc.
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"project create failed: {exc}") from exc
    await record_audit(db, action="create_project", actor_id=admin.id, target_type="project", target_id=str(proj.id))
    await db.commit()
    await db.refresh(proj)
    return ProjectOut.model_validate(proj)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    if body.name is not None:
        proj.name = body.name.strip()
    if body.is_active is not None:
        proj.is_active = body.is_active
    if body.default_persona_id is not None:
        proj.default_persona_id = body.default_persona_id
    await record_audit(db, action="update_project", actor_id=admin.id, target_type="project", target_id=str(proj.id))
    await db.commit()
    await db.refresh(proj)
    return ProjectOut.model_validate(proj)


@router.post("/{project_id}/reindex", response_model=ProjectOut)
async def reindex_project(
    project_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    """Rebuild this project's catalog card (the master-index entry) from approved units."""
    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    from app.graph.llm_real import GeminiEmbedder, make_minimax_llm_json
    from app.services.knowledge_pipeline import KnowledgePipeline

    try:
        await KnowledgePipeline(db, GeminiEmbedder(), make_minimax_llm_json()).build_project_index(proj.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"index rebuild failed: {exc}") from exc
    await db.refresh(proj)
    return ProjectOut.model_validate(proj)
