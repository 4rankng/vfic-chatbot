"""Projects ("product catalog") admin API — thin HTTP layer over :class:`ProjectService`.

All CRUD, master-index rebuild, and worker product-feature CRUD/re-extraction live in
``app.services.project_service``; this router only validates input, delegates, and
serializes the response.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import User
from app.schemas.projects import (
    FeatureListResponse,
    FeatureOut,
    FeatureUpdate,
    ProjectCreate,
    ProjectListResponse,
    ProjectOut,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/knowledge/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    is_active: bool | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    rows = await ProjectService(db).list(is_active)
    return ProjectListResponse(data=[ProjectOut.model_validate(p) for p in rows], total=len(rows))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(db).create(body, admin))


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(db).update(project_id, body, admin))


@router.post("/{project_id}/reindex", response_model=ProjectOut)
async def reindex_project(
    project_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(db).reindex(project_id))


@router.get("/{project_id}/features", response_model=FeatureListResponse)
async def list_project_features(
    project_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> FeatureListResponse:
    """List the project's 16 extracted worker product features (catalog order)."""
    return await ProjectService(db).list_features(project_id)


@router.patch("/{project_id}/features/{feature_id}", response_model=FeatureOut)
async def update_project_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: FeatureUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FeatureOut:
    """Admin review/edit of one extracted feature value; re-syncs product highlights."""
    return await ProjectService(db).update_feature(project_id, feature_id, body, admin)


@router.post("/{project_id}/features/extract", response_model=FeatureListResponse)
async def extract_project_features(
    project_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> FeatureListResponse:
    """Synchronously re-extract the 16 product features from the project's latest posting."""
    return await ProjectService(db).extract_features(project_id, admin)
