"""Recruitment knowledge-project admin API — thin HTTP layer over :class:`ProjectService`.

All CRUD, master-index rebuild, and worker knowledge-feature CRUD/re-extraction live
in ``app.services.project``; this router only validates input, delegates, and
serializes the response. Domain exceptions raised by the service are mapped to HTTP
status codes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin, require_recruiter
from app.core.db import get_db
from app.models.user import User
from app.schemas.projects import (
    BusTimetableResponse,
    FeatureListResponse,
    FeatureOut,
    FeatureUpdate,
    ProjectFaqCreate,
    ProjectFaqOut,
    ProjectFaqResponse,
    ProjectFaqUpdate,
    ProjectCreate,
    ProjectListResponse,
    ProjectOut,
    ProjectUpdate,
)
from app.services.project import ProjectService

router = APIRouter(prefix="/knowledge/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    is_active: bool | None = Query(None),
    q: str | None = Query(
        None, description="Case-insensitive search over project name, slug, summary"
    ),
    sort: str | None = Query(
        None, description="Sort field (name, created_at, updated_at, is_active)"
    ),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    data, total = await ProjectService(db).list_with_readiness(
        is_active,
        page=page,
        per_page=per_page,
        sort_by=sort,
        order=order,
        q=q,
    )
    return ProjectListResponse(data=data, total=total)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return await ProjectService(db).get_with_readiness(project_id)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(db).create(body, admin))


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    actor: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(db).update(project_id, body, actor))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ProjectService(db).delete(project_id, admin)


@router.post("/{project_id}/reindex", response_model=ProjectOut)
async def reindex_project(
    project_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(db).reindex(project_id))


@router.get("/{project_id}/features", response_model=FeatureListResponse)
async def list_project_features(
    project_id: uuid.UUID,
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> FeatureListResponse:
    """List the project's active extracted worker product features (catalog order)."""
    return await ProjectService(db).list_features(project_id)


@router.get("/{project_id}/bus-timetable", response_model=BusTimetableResponse)
async def list_project_bus_timetable(
    project_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=25),
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> BusTimetableResponse:
    """List the project's structured bus routes with ordered pickup stops."""
    return await ProjectService(db).list_bus_timetable(project_id, page=page, per_page=per_page)


@router.get("/{project_id}/faq", response_model=ProjectFaqResponse)
async def list_project_faq(
    project_id: uuid.UUID,
    limit: int = Query(12, ge=1, le=50),
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectFaqResponse:
    """List the project's published FAQ answers."""
    return await ProjectService(db).list_faq(project_id, limit=limit)


@router.post(
    "/{project_id}/faq",
    response_model=ProjectFaqOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_faq(
    project_id: uuid.UUID,
    body: ProjectFaqCreate,
    actor: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectFaqOut:
    """Create a question/answer pair in the project's FAQ knowledge."""
    return await ProjectService(db).create_faq(project_id, body, actor)


@router.patch("/{project_id}/faq/{faq_id}", response_model=ProjectFaqOut)
async def update_project_faq(
    project_id: uuid.UUID,
    faq_id: uuid.UUID,
    body: ProjectFaqUpdate,
    actor: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectFaqOut:
    """Edit a question/answer pair in the project's FAQ knowledge."""
    return await ProjectService(db).update_faq(project_id, faq_id, body, actor)


@router.delete("/{project_id}/faq/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_faq(
    project_id: uuid.UUID,
    faq_id: uuid.UUID,
    actor: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a question/answer pair from the project's FAQ knowledge."""
    await ProjectService(db).delete_faq(project_id, faq_id, actor)


@router.patch("/{project_id}/features/{feature_id}", response_model=FeatureOut)
async def update_project_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: FeatureUpdate,
    actor: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> FeatureOut:
    """Recruiter/admin review-edit of one feature value; re-syncs product highlights."""
    return await ProjectService(db).update_feature(project_id, feature_id, body, actor)


@router.post("/{project_id}/features/extract", response_model=FeatureListResponse)
async def extract_project_features(
    project_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> FeatureListResponse:
    """Synchronously re-extract active product features from the project's latest posting."""
    return await ProjectService(db).extract_features(project_id, admin)
