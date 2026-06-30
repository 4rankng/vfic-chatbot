"""Projects ("product catalog") admin API — thin HTTP layer over :class:`ProjectService`.

All CRUD, master-index rebuild, and worker product-feature CRUD/re-extraction live in
``app.services.project``; this router only validates input, delegates, and serializes
the response. Domain exceptions raised by the service are mapped to HTTP status codes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin, require_recruiter
from app.core.db import get_db
from app.models.user import User
from app.schemas.projects import (
    BusTimetableResponse,
    FeatureListResponse,
    FeatureOut,
    FeatureUpdate,
    ProjectFaqResponse,
    ProjectCreate,
    ProjectListResponse,
    ProjectOut,
    ProjectUpdate,
)
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, UpstreamError
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
    try:
        result = await ProjectService(db).get_with_readiness(project_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return result


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    try:
        result = await ProjectService(db).create(body, admin)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ProjectOut.model_validate(result)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    actor: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    try:
        result = await ProjectService(db).update(project_id, body, actor)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return ProjectOut.model_validate(result)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await ProjectService(db).delete(project_id, admin)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/{project_id}/reindex", response_model=ProjectOut)
async def reindex_project(
    project_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    try:
        result = await ProjectService(db).reindex(project_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UpstreamError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return ProjectOut.model_validate(result)


@router.get("/{project_id}/features", response_model=FeatureListResponse)
async def list_project_features(
    project_id: uuid.UUID,
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> FeatureListResponse:
    """List the project's active extracted worker product features (catalog order)."""
    try:
        result = await ProjectService(db).list_features(project_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return result


@router.get("/{project_id}/bus-timetable", response_model=BusTimetableResponse)
async def list_project_bus_timetable(
    project_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(6, ge=1, le=25),
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> BusTimetableResponse:
    """List the project's structured bus routes with ordered pickup stops."""
    try:
        result = await ProjectService(db).list_bus_timetable(
            project_id, page=page, per_page=per_page
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return result


@router.get("/{project_id}/faq", response_model=ProjectFaqResponse)
async def list_project_faq(
    project_id: uuid.UUID,
    limit: int = Query(12, ge=1, le=50),
    _user: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> ProjectFaqResponse:
    """List the project's published FAQ answers."""
    try:
        result = await ProjectService(db).list_faq(project_id, limit=limit)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return result


@router.patch("/{project_id}/features/{feature_id}", response_model=FeatureOut)
async def update_project_feature(
    project_id: uuid.UUID,
    feature_id: uuid.UUID,
    body: FeatureUpdate,
    actor: User = Depends(require_recruiter),
    db: AsyncSession = Depends(get_db),
) -> FeatureOut:
    """Recruiter/admin review-edit of one feature value; re-syncs product highlights."""
    try:
        result = await ProjectService(db).update_feature(project_id, feature_id, body, actor)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return result


@router.post("/{project_id}/features/extract", response_model=FeatureListResponse)
async def extract_project_features(
    project_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> FeatureListResponse:
    """Synchronously re-extract active product features from the project's latest posting."""
    try:
        result = await ProjectService(db).extract_features(project_id, admin)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UpstreamError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return result
