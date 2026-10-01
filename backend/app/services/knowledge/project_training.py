"""Durable, resumable category training owned by a retained source document."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.schemas.knowledge import ProjectTrainingPlan
from app.services.knowledge.category_markdown import parse_category_markdown
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.shared.domain.errors import ConflictError
from app.services.knowledge.training_guard import ensure_training_owner


TRAINING_LEASE_SECONDS = 3_900


def validate_training_plan(plan: ProjectTrainingPlan) -> None:
    """Validate every category before any source or revision is written."""
    documents = {
        write.key: parse_category_markdown(write.key, write.content) for write in plan.writes
    }
    jobs = documents.get("jobs")
    if jobs is None:
        return  # References to existing jobs are checked by the category lifecycle.
    job_ids = {job.id for job in jobs.jobs}
    for document in documents.values():
        for record in getattr(document, document.category.value):
            if set(getattr(record, "job_ids", [])) - job_ids:
                raise ValueError("Training categories reference jobs absent from the jobs proposal")


def training_progress(doc: KnowledgeDocument, **changes) -> None:
    meta = dict(doc.digest_meta or {})
    meta["project_training"] = {**meta.get("project_training", {}), **changes}
    doc.digest_meta = meta


class ProjectTrainingService:
    def __init__(
        self,
        db,
        *,
        categories: KnowledgeCategoryService | None = None,
        processing_token: uuid.UUID | None = None,
    ) -> None:
        self.db = db
        self.categories = categories or KnowledgeCategoryService(db)
        self.processing_token = processing_token or uuid.uuid4()

    async def claim(self, doc: KnowledgeDocument) -> bool:
        """Serialize duplicate deliveries without holding a DB transaction during I/O."""
        locked = await self.db.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == doc.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked is None:
            return False
        if locked.status == KnowledgeStatus.ARCHIVED:
            await self.db.commit()
            return False
        if (locked.digest_meta or {}).get("project_training", {}).get("status") == "COMPLETED":
            await self.db.commit()
            return False  # Late duplicate delivery; an explicit process call resets QUEUED.
        training = dict((locked.metadata_ or {}).get("project_training") or {})
        lease = training.get("lease_expires_at")
        if lease and datetime.fromisoformat(lease) > datetime.now(UTC):
            await self.db.commit()
            return False
        training["lease_expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=TRAINING_LEASE_SECONDS)
        ).isoformat()
        training["processing_token"] = str(self.processing_token)
        locked.metadata_ = {**(locked.metadata_ or {}), "project_training": training}
        training_progress(locked, status="PROCESSING", error=None)
        await self.db.commit()
        return True

    async def _guard(self, doc: KnowledgeDocument) -> None:
        doc.metadata_ = await ensure_training_owner(
            self.db, doc.id, doc.project_id, self.processing_token
        )

    async def run(self, doc: KnowledgeDocument, embedder) -> None:
        training = dict((doc.metadata_ or {})["project_training"])
        plan = ProjectTrainingPlan.model_validate({"writes": training["writes"]})
        validate_training_plan(plan)
        actor = SimpleNamespace(id=uuid.UUID(training["actor_id"]))
        completed = list((doc.digest_meta or {}).get("project_training", {}).get("completed", []))
        revision_ids = dict(training.get("revision_ids", {}))
        # Jobs lead the sequence because sibling categories may reference them.
        writes = sorted(plan.writes, key=lambda write: write.key != "jobs")
        for write in writes:
            # A later source upload supersedes an interrupted older batch. Do
            # not let a retry replace the recruiter's newer project knowledge.
            await self._guard(doc)
            if write.key.value in completed:
                active = await self.db.scalar(
                    select(KnowledgeCategory.active_revision_id).where(
                        KnowledgeCategory.project_id == doc.project_id,
                        KnowledgeCategory.category_key == write.key.value,
                    )
                )
                if str(active) != revision_ids.get(write.key.value):
                    raise ConflictError("Project knowledge changed after this training checkpoint")
                continue
            training_progress(
                doc, status="PROCESSING", current=write.key.value, completed=completed
            )
            doc.stage = "TRAINING_CATEGORIES"
            await self.db.commit()
            revision, _receipt = await self.categories.stage_replacement(
                project_id=doc.project_id,
                category_key=write.key,
                filename=write.filename,
                source_markdown=write.content,
                actor=actor,
                schedule=False,
            )
            revision_ids[write.key.value] = str(revision.id)
            await self._guard(doc)
            doc.metadata_ = {
                **(doc.metadata_ or {}),
                "project_training": {**training, "revision_ids": revision_ids},
            }
            await self.db.commit()
            await self.categories.activate_revision(
                revision.id,
                embedder,
                training_document_id=doc.id,
                training_token=self.processing_token,
            )
            await self.db.refresh(revision)
            if revision.status is not KnowledgeCategoryRevisionStatus.ACTIVE:
                raise ConflictError("Training category was not confirmed active")
            completed.append(write.key.value)
            await self._guard(doc)
            training_progress(doc, completed=list(completed))
            await self.db.commit()
        await self._guard(doc)
        doc.metadata_ = {
            **(doc.metadata_ or {}),
            "project_training": {
                **training,
                "revision_ids": revision_ids,
                "lease_expires_at": None,
                "processing_token": None,
            },
        }
        training_progress(doc, status="COMPLETED", current=None, completed=completed, error=None)
        doc.status = "PUBLISHED"
        doc.stage = "PUBLISHED"
        doc.error = None
        await self.db.commit()


class BatchCategoryEmbedder:
    """Reuse the same provider and fallback policy as document embeddings."""

    def __init__(self, embedder) -> None:
        self.embedder = embedder

    async def batch(self, texts: list[str]) -> list[list[float]]:
        from app.core.embedding import embed_with_fallback

        batch = getattr(self.embedder, "batch", None)
        if callable(batch):
            return await embed_with_fallback(batch, texts, label="project training embedder")
        return [await self.embedder(text) for text in texts]
