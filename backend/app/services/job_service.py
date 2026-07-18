"""Job CRUD + semantic search over the documents view."""

from __future__ import annotations

from typing import Awaitable, Callable

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.core.vector import vec_literal
from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.services.retrieval import RetrievalRepository

Embedder = Callable[[str], Awaitable[list[float]]]


class JobService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, job_id) -> Job | None:
        return await self.db.scalar(
            self._authority_query().where(Job.id == job_id)
        )

    async def list(
        self, *, status_: JobStatus | None = None, page: int = 1, per_page: int = 25
    ) -> tuple[list[Job], int]:
        q = self._authority_query()
        if status_ is not None:
            q = q.where(Job.status == status_)
        total = await self.db.scalar(select(func.count()).select_from(q.subquery()))
        rows = (
            await self.db.scalars(
                q.order_by(desc(Job.created_at)).offset((page - 1) * per_page).limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    @staticmethod
    def _authority_query():
        return (
            select(Job)
            .join(Company, Company.id == Job.company_id)
            .join(Project, Project.id == Company.project_id)
            .where(
                or_(
                    and_(
                        Project.category_authority_started.is_(True),
                        Job.source_category_revision_id.is_not(None),
                    ),
                    and_(
                        Project.category_authority_started.is_(False),
                        Job.source_category_revision_id.is_(None),
                    ),
                )
            )
        )

    async def create(self, data: dict) -> Job:
        job = Job(**data)
        self.db.add(job)
        await self.db.commit()
        await bump_cache_version("jobs")
        await self.db.refresh(job)
        return job

    async def update(self, job: Job, changes: dict) -> Job:
        for k, v in changes.items():
            if hasattr(job, k):
                setattr(job, k, v)
        await self.db.commit()
        await bump_cache_version("jobs")
        await self.db.refresh(job)
        return job

    async def search(self, embedder: Embedder, query: str, top_k: int = 25) -> list[dict]:
        emb = vec_literal(await embedder(query))
        rows = await RetrievalRepository(self.db).match_documents(emb, top_k, "{}")
        return [
            {"id": str(r.id), "content": r.content, "similarity": float(r.similarity)} for r in rows
        ]
