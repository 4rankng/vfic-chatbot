"""Durable, resumable category training owned by a retained source document."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Awaitable, Callable

from sqlalchemy import select

from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.schemas.knowledge import ProjectTrainingPlan
from app.services.knowledge.canonical import checksum_text
from app.services.knowledge.category_markdown import parse_category_markdown
from app.services.knowledge.category_service import KnowledgeCategoryService
from app.services.knowledge.training_guard import ensure_training_owner
from app.shared.domain.errors import ConflictError


TRAINING_LEASE_SECONDS = 3_900


def validate_training_plan(plan: ProjectTrainingPlan) -> None:
    """Validate every category before any source or revision is written."""
    for write in plan.writes:
        parse_category_markdown(write.key, write.content)


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
        batch=None,
    ) -> None:
        self.db = db
        self.categories = categories or KnowledgeCategoryService(db)
        self.processing_token = processing_token or uuid.uuid4()
        if batch is None:
            from app.services.knowledge.category_batch import TrainingCategoryBatch

            batch = TrainingCategoryBatch(db, self.categories, self.processing_token)
        self.batch = batch

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
        training_progress(locked, status="PROCESSING", current=None, error=None)
        await self.db.commit()
        return True

    async def _guard(self, doc: KnowledgeDocument) -> None:
        if doc.project_id is None:
            raise ConflictError("Project training requires a project")
        doc.metadata_ = await ensure_training_owner(
            self.db, doc.id, doc.project_id, self.processing_token
        )

    async def prepare_plan(self, doc: KnowledgeDocument, llm_json) -> None:
        """Map a retained source before any digest, features or category writes."""
        from app.services.knowledge.extraction import (
            CategoryPlanExtractionError,
            extract_category_plan,
        )

        training = dict((doc.metadata_ or {})["project_training"])
        if not training.get("auto_extract"):
            plan = ProjectTrainingPlan.model_validate({"writes": training["writes"]})
            validate_training_plan(plan)
            training_progress(doc, planned=[write.key.value for write in plan.writes])
            return
        await self._guard(doc)
        await self.batch.check_extraction_baseline(doc)
        # Release every project/source lock before provider work.
        doc.status = KnowledgeStatus.PROCESSING
        doc.stage = "EXTRACTING_CATEGORIES"
        await self.db.commit()
        training = dict(doc.metadata_["project_training"])
        checkpoint = training.get("extraction") or None
        if training.get("writes"):
            plan = ProjectTrainingPlan.model_validate({"writes": training["writes"]})
            validate_training_plan(plan)
            source_sha256 = hashlib.sha256((doc.raw_text or "").encode()).hexdigest()
            if (
                not checkpoint
                or checkpoint.get("status") != "COMPLETED"
                or checkpoint.get("source_sha256") != source_sha256
                or training.get("extracted_plan_sha256") != checksum_text(plan.model_dump_json())
            ):
                raise CategoryPlanExtractionError("Saved category plan does not match the source")
            training_progress(doc, planned=[write.key.value for write in plan.writes])
            await self.db.commit()
            return

        async def save_checkpoint(state):
            await self._guard(doc)
            await self.batch.check_extraction_baseline(doc)
            current = dict(doc.metadata_["project_training"])
            doc.metadata_ = {**doc.metadata_, "project_training": {**current, "extraction": state}}
            training_progress(
                doc,
                source_sections_total=state["total_sections"],
                source_sections_completed=state["completed_sections"],
                covered_categories=state["covered_categories"],
                missing_categories=state["missing_categories"],
            )
            await self.db.commit()

        plan = await extract_category_plan(
            doc.raw_text or "",
            llm_json,
            checkpoint=checkpoint,
            on_checkpoint=save_checkpoint,
        )
        if plan is None:
            raise CategoryPlanExtractionError("Source has no recruitment category facts")
        validate_training_plan(plan)
        await self._guard(doc)
        await self.batch.check_extraction_baseline(doc)
        training = dict(doc.metadata_["project_training"])
        doc.metadata_ = {
            **doc.metadata_,
            "project_training": {
                **training,
                "writes": plan.model_dump(mode="json")["writes"],
                "extracted_plan_sha256": checksum_text(plan.model_dump_json()),
            },
        }
        training_progress(doc, planned=[write.key.value for write in plan.writes])
        await self.db.commit()

    async def run(self, doc: KnowledgeDocument, embedder) -> None:
        training = dict((doc.metadata_ or {})["project_training"])
        plan = ProjectTrainingPlan.model_validate({"writes": training["writes"]})
        validate_training_plan(plan)
        actor = SimpleNamespace(id=uuid.UUID(training["actor_id"]))
        completed = list((doc.digest_meta or {}).get("project_training", {}).get("completed", []))
        # Publish one coherent pointer graph after every category is prepared.
        # Legacy projects retain shadow authority until explicit category cutover.
        writes = plan.writes
        await self._guard(doc)
        revisions = await self.batch.stage(doc, plan, actor)
        for write, revision in zip(writes, revisions, strict=True):
            await self._guard(doc)
            training_progress(
                doc, status="PROCESSING", current=write.key.value, completed=completed
            )
            doc.stage = "TRAINING_CATEGORIES"
            await self.db.commit()
            await self.batch.prepare(doc, revision, embedder)
        await self._guard(doc)
        await self.batch.publish(doc, revisions)
        training = dict(doc.metadata_["project_training"])
        doc.metadata_ = {
            **(doc.metadata_ or {}),
            "project_training": {
                **training,
                "lease_expires_at": None,
                "processing_token": None,
            },
        }
        training_progress(
            doc,
            status="COMPLETED",
            current=None,
            completed=[write.key.value for write in writes],
            error=None,
        )
        doc.status = KnowledgeStatus.PUBLISHED
        doc.stage = "PUBLISHED"
        doc.error = None
        await self.db.commit()
        await self.batch.repair_caches()


class BatchCategoryEmbedder:
    """Reuse the same provider and fallback policy as document embeddings."""

    def __init__(self, embedder: Callable[[str], Awaitable[list[float]]]) -> None:
        self.embedder = embedder

    async def batch(self, texts: list[str]) -> list[list[float]]:
        from app.core.embedding import BatchEmbeddingProvider, embed_with_fallback

        single_embedder = self.embedder
        if isinstance(self.embedder, BatchEmbeddingProvider) and callable(self.embedder.batch):
            return await embed_with_fallback(
                self.embedder.batch, texts, label="project training embedder"
            )
        return [await single_embedder(text) for text in texts]
