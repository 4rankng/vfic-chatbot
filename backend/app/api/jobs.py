"""Jobs API: admin CRUD + recruiter view + semantic search."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_admin
from app.core.db import get_db
from app.models.job import JobStatus
from app.models.user import User
from app.schemas.job import JobCreate, JobListResponse, JobOut, JobSearchRequest, JobSearchResult, JobUpdate
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status_: JobStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    rows, total = await JobService(db).list(status_=status_, page=page, per_page=per_page)
    return JobListResponse(data=[JobOut.model_validate(r) for r in rows], total=total)


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(body: JobCreate, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> JobOut:
    return JobOut.model_validate(await JobService(db).create(body.model_dump()))


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await JobService(db).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobOut.model_validate(job)


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(job_id: uuid.UUID, body: JobUpdate, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await JobService(db).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobOut.model_validate(await JobService(db).update(job, body.model_dump(exclude_unset=True)))


@router.post("/{job_id}/archive", response_model=JobOut)
async def archive_job(job_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await JobService(db).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobOut.model_validate(await JobService(db).update(job, {"status": JobStatus.ARCHIVED}))


@router.post("/{job_id}/mark-full", response_model=JobOut)
async def mark_full(job_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await JobService(db).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobOut.model_validate(await JobService(db).update(job, {"status": JobStatus.FULL}))


@router.post("/search", response_model=list[JobSearchResult])
async def search_jobs(
    body: JobSearchRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[JobSearchResult]:
    from app.graph.llm_real import GeminiEmbedder

    rows = await JobService(db).search(GeminiEmbedder(), body.query, body.top_k)
    return [JobSearchResult(content=r["content"], similarity=r["similarity"]) for r in rows]
