"""Job CRUD + semantic search (match_documents over the documents VIEW, the same
path the bot's search_jobs tool uses)."""
from __future__ import annotations

from typing import Awaitable, Callable

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.models.job import Job, JobStatus
from app.services.retrieval import RetrievalRepository

Embedder = Callable[[str], Awaitable[list[float]]]


class JobService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, job_id) -> Job | None:
        return await self.db.get(Job, job_id)

    async def list(self, *, status_: JobStatus | None = None, page: int = 1, per_page: int = 25) -> tuple[list[Job], int]:
        q = select(Job)
        if status_ is not None:
            q = q.where(Job.status == status_)
        total = await self.db.scalar(select(func.count()).select_from(q.subquery()))
        rows = (await self.db.scalars(q.order_by(desc(Job.created_at)).offset((page - 1) * per_page).limit(per_page))).all()
        return list(rows), int(total or 0)

    async def create(self, data: dict) -> Job:
        job = Job(**data)
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def update(self, job: Job, changes: dict) -> Job:
        for k, v in changes.items():
            if hasattr(job, k):
                setattr(job, k, v)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def search(self, embedder: Embedder, query: str, top_k: int = 25) -> list[dict]:
        emb = vec_literal(await embedder(query))
        rows = await RetrievalRepository(self.db).match_documents(emb, top_k, "{}")
        return [{"id": str(r.id), "content": r.content, "similarity": float(r.similarity)} for r in rows]
