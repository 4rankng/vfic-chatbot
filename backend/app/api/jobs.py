"""Jobs API: admin CRUD + recruiter view + semantic search."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user, require_admin
from app.api.installation_dependencies import require_capability_or_legacy
from app.api.provider_dependencies import get_embedder
from app.project_knowledge.infrastructure.api_dependencies import get_project_knowledge_db
from app.schemas.job import (
    JobCreate,
    JobStatus,
    JobListResponse,
    JobOut,
    JobSearchRequest,
    JobSearchResult,
    JobUpdate,
)
from app.services.job_service import JobService
from app.shared.domain.errors import ConflictError, NotFoundError
from app.shared.infrastructure.rate_limits import enforce_jobs_search_rate_limit

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_capability_or_legacy("job_advisory"))],
)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status_: JobStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    _user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> JobListResponse:
    rows, total = await JobService(db).list(status_=status_, page=page, per_page=per_page)
    return JobListResponse(data=[JobOut.model_validate(r) for r in rows], total=total)


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> JobOut:
    raise ConflictError("Jobs are read-only projections; update the Project Jobs YAML category")


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    _user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> JobOut:
    job = await JobService(db).get(job_id)
    if job is None:
        raise NotFoundError("job not found")
    return JobOut.model_validate(job)


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: uuid.UUID,
    body: JobUpdate,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> JobOut:
    raise ConflictError("Jobs are read-only projections; update the Project Jobs YAML category")


@router.post("/{job_id}/archive", response_model=JobOut)
async def archive_job(
    job_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> JobOut:
    raise ConflictError("Jobs are read-only projections; remove the job from the Jobs YAML category")


@router.post("/{job_id}/mark-full", response_model=JobOut)
async def mark_full(
    job_id: uuid.UUID,
    _admin: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> JobOut:
    raise ConflictError("Jobs have no manual status; remove unavailable jobs from the Jobs YAML")


@router.post("/search", response_model=list[JobSearchResult])
async def search_jobs(
    body: JobSearchRequest,
    embedder=Depends(get_embedder),
    _user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_project_knowledge_db),
) -> list[JobSearchResult]:
    # SEC-04: one embedding call per request, so cap it per user.
    await enforce_jobs_search_rate_limit(_user.id)
    rows = await JobService(db).search(embedder, body.query, body.top_k)
    return [JobSearchResult(content=r["content"], similarity=r["similarity"]) for r in rows]
