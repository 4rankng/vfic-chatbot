"""Independent Project RAG-category lifecycle and deterministic projections."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any, Protocol

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.user import User
from app.schemas.knowledge_categories import CategoryDocument, KnowledgeCategoryKey
from app.schemas.project_knowledge import CategoryCatalogItemOut, CategorySourceOut
from app.services.audit_service import record_audit
from app.shared.domain.errors import ConflictError, NotFoundError, UpstreamError
from app.services.knowledge.category_contracts import (
    CATEGORY_DEFINITIONS,
    canonical_category_json,
    category_checksum,
    get_category_definition,
    parse_category_yaml,
    validate_category_payload,
    validate_job_references,
)
from app.services.knowledge.category_projections import (
    CategoryProjectionWriter,
    SqlAlchemyCategoryProjectionWriter,
)
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo
from app.project_knowledge.application.jobs import (
    EnqueueReceiptUnknown,
    ProjectKnowledgeJobs,
)


class CategoryEmbedder(Protocol):
    async def batch(self, texts: list[str]) -> list[list[float]]: ...


CATEGORY_PROCESSING_LEASE_SECONDS = 3_900
MAX_CATEGORY_PROCESSING_ATTEMPTS = 3
CATEGORY_ACTIVATION_FAILURE = "category_activation_failed"
CATEGORY_RETRY_EXHAUSTED = "category_retry_exhausted"


class CategoryActivationError(RuntimeError):
    def __init__(self, code: str = CATEGORY_ACTIVATION_FAILURE) -> None:
        super().__init__(code)
        self.code = code


class KnowledgeCategoryService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        jobs: ProjectKnowledgeJobs | None = None,
        projection_writer: CategoryProjectionWriter | None = None,
    ) -> None:
        self.db = db
        self._jobs = jobs
        self._cache_repair = None
        self._projection_writer = (
            projection_writer or SqlAlchemyCategoryProjectionWriter(db)
        )

    def _job_scheduler(self) -> ProjectKnowledgeJobs:
        if self._jobs is None:
            from app.composition.project_knowledge_jobs import build_project_knowledge_jobs

            self._jobs = build_project_knowledge_jobs()
        return self._jobs

    def _cache_repairer(self) -> Any:
        if self._cache_repair is None:
            from app.project_knowledge.infrastructure.cache import (
                RedisProjectKnowledgeCacheRepair,
            )

            self._cache_repair = RedisProjectKnowledgeCacheRepair()
        return self._cache_repair

    async def list_catalog(self, project_id: uuid.UUID) -> list[CategoryCatalogItemOut]:
        await self._require_rag_project(project_id)
        categories = list(
            (
                await self.db.scalars(
                    select(KnowledgeCategory)
                    .where(KnowledgeCategory.project_id == project_id)
                    .order_by(KnowledgeCategory.created_at, KnowledgeCategory.category_key)
                )
            ).all()
        )
        active_ids = [row.active_revision_id for row in categories if row.active_revision_id]
        revisions = {
            row.id: row
            for row in (
                (
                    await self.db.scalars(
                        select(KnowledgeCategoryRevision).where(
                            KnowledgeCategoryRevision.id.in_(active_ids)
                        )
                    )
                ).all()
                if active_ids
                else []
            )
        }
        latest_by_category: dict[uuid.UUID, KnowledgeCategoryRevision] = {}
        if categories:
            latest_numbers = (
                select(
                    KnowledgeCategoryRevision.category_id,
                    func.max(KnowledgeCategoryRevision.revision_no).label("revision_no"),
                )
                .where(KnowledgeCategoryRevision.category_id.in_([row.id for row in categories]))
                .group_by(KnowledgeCategoryRevision.category_id)
                .subquery()
            )
            revision_rows = (
                await self.db.scalars(
                    select(KnowledgeCategoryRevision)
                    .join(
                        latest_numbers,
                        (latest_numbers.c.category_id == KnowledgeCategoryRevision.category_id)
                        & (
                            latest_numbers.c.revision_no
                            == KnowledgeCategoryRevision.revision_no
                        ),
                    )
                )
            ).all()
            for revision_row in revision_rows:
                latest_by_category.setdefault(revision_row.category_id, revision_row)
        rows_by_key = {row.category_key: row for row in categories}
        output: list[CategoryCatalogItemOut] = []
        for definition in CATEGORY_DEFINITIONS:
            category = rows_by_key.get(definition.key.value)
            revision = revisions.get(category.active_revision_id) if category else None
            latest = latest_by_category.get(category.id) if category else None
            output.append(
                CategoryCatalogItemOut(
                    key=definition.key,
                    label_vi=definition.label_vi,
                    active_revision_id=revision.id if revision else None,
                    active_revision_no=revision.revision_no if revision else None,
                    active_checksum=revision.content_sha256 if revision else None,
                    latest_revision_id=latest.id if latest else None,
                    latest_revision_no=latest.revision_no if latest else None,
                    status=latest.status if latest else None,
                    error_message=latest.error_message if latest else None,
                    updated_at=(latest.activated_at or latest.created_at if latest else category.updated_at)
                    if category
                    else None,
                )
            )
        return output

    async def stage_replacement(
        self,
        *,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
        filename: str,
        source_yaml: str,
        actor: User,
    ) -> tuple[KnowledgeCategoryRevision, str]:
        await self._require_rag_project(project_id)
        try:
            document = parse_category_yaml(category_key, source_yaml)
            await self._validate_active_job_references(project_id, document)
        except ValueError as exc:
            raise ConflictError("Category YAML failed validation") from exc
        category = await self._locked_category(project_id, category_key)
        checksum = category_checksum(document)
        existing = await self.db.scalar(
            select(KnowledgeCategoryRevision)
            .where(
                KnowledgeCategoryRevision.category_id == category.id,
                KnowledgeCategoryRevision.source_filename == filename,
                KnowledgeCategoryRevision.source_yaml == source_yaml,
                KnowledgeCategoryRevision.status.in_(
                    (
                        KnowledgeCategoryRevisionStatus.STAGED,
                        KnowledgeCategoryRevisionStatus.PROCESSING,
                        KnowledgeCategoryRevisionStatus.ACTIVE,
                        KnowledgeCategoryRevisionStatus.FAILED,
                    )
                ),
            )
            .order_by(KnowledgeCategoryRevision.revision_no.desc())
            .limit(1)
        )
        if existing is not None:
            revision = existing
            await self.db.commit()
        else:
            latest = await self.db.scalar(
                select(func.max(KnowledgeCategoryRevision.revision_no)).where(
                    KnowledgeCategoryRevision.category_id == category.id
                )
            )
            revision = KnowledgeCategoryRevision(
                category_id=category.id,
                revision_no=int(latest or 0) + 1,
                status=KnowledgeCategoryRevisionStatus.STAGED,
                source_filename=filename,
                source_yaml=source_yaml,
                normalized_payload=document.model_dump(mode="json"),
                content_sha256=checksum,
                created_by=actor.id,
            )
            self.db.add(revision)
            await self.db.flush()
            await record_audit(
                self.db,
                action="stage_project_knowledge_category",
                actor_id=actor.id,
                target_type="knowledge_category_revision",
                target_id=str(revision.id),
                payload={"project_id": str(project_id), "category": category_key.value},
            )
            await self.db.commit()
            await self.db.refresh(revision)

        if revision.status is KnowledgeCategoryRevisionStatus.ACTIVE:
            return revision, f"category-revision-{revision.id}"
        if (
            revision.status is KnowledgeCategoryRevisionStatus.FAILED
            and revision.attempt_count >= MAX_CATEGORY_PROCESSING_ATTEMPTS
        ):
            revision.failure_code = CATEGORY_RETRY_EXHAUSTED
            revision.error_message = "Category processing retry limit reached"
            await self.db.commit()
            raise ConflictError(
                "Category processing retry limit reached; submit corrected content"
            )
        if (
            revision.status is KnowledgeCategoryRevisionStatus.PROCESSING
            and revision.lease_expires_at is not None
            and revision.lease_expires_at > datetime.now(UTC)
        ):
            return revision, f"category-revision-{revision.id}"

        try:
            job_id = self._job_scheduler().process_category_revision(revision.id)
        except EnqueueReceiptUnknown as exc:
            raise UpstreamError(
                "Queue receipt is temporarily unconfirmed; retrying the same content is safe"
            ) from exc
        except Exception as exc:
            if revision.status in {
                KnowledgeCategoryRevisionStatus.STAGED,
                KnowledgeCategoryRevisionStatus.FAILED,
            }:
                revision.status = KnowledgeCategoryRevisionStatus.FAILED
                revision.error_message = "The processing queue is unavailable"
                await self.db.commit()
            raise UpstreamError(
                "Could not queue the category update; the active content is unchanged"
            ) from exc
        return revision, job_id

    async def get_active_source(
        self,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
    ) -> CategorySourceOut:
        await self._require_rag_project(project_id)
        category = await self.db.scalar(
            select(KnowledgeCategory).where(
                KnowledgeCategory.project_id == project_id,
                KnowledgeCategory.category_key == category_key.value,
            )
        )
        if category is None or category.active_revision_id is None:
            raise NotFoundError("Knowledge category has no active content")
        revision = await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
        if revision is None:
            raise NotFoundError("Active knowledge category revision not found")
        definition = get_category_definition(category_key)
        return CategorySourceOut(
            key=category_key,
            label_vi=definition.label_vi,
            revision_id=revision.id,
            revision_no=revision.revision_no,
            filename=revision.source_filename,
            content=revision.source_yaml,
            checksum=revision.content_sha256,
            updated_at=revision.activated_at or revision.created_at,
        )

    async def activate_revision(
        self,
        revision_id: uuid.UUID,
        embedder: CategoryEmbedder,
        *,
        start_category_authority: bool = False,
        claim_token: uuid.UUID | None = None,
    ) -> None:
        started_at = monotonic()
        claim_token = claim_token or uuid.uuid4()
        revision = await self.db.get(KnowledgeCategoryRevision, revision_id)
        if revision is None:
            raise NotFoundError("Category revision not found")
        if revision.status is KnowledgeCategoryRevisionStatus.ACTIVE:
            await self._repair_caches()
            return
        category = await self.db.get(KnowledgeCategory, revision.category_id)
        if category is None:
            raise NotFoundError("Category not found")

        now = datetime.now(UTC)
        claim = await self.db.execute(
            update(KnowledgeCategoryRevision)
            .where(
                KnowledgeCategoryRevision.id == revision_id,
                KnowledgeCategoryRevision.attempt_count < MAX_CATEGORY_PROCESSING_ATTEMPTS,
                or_(
                    KnowledgeCategoryRevision.status.in_(
                        [
                            KnowledgeCategoryRevisionStatus.STAGED,
                            KnowledgeCategoryRevisionStatus.FAILED,
                        ]
                    ),
                    and_(
                        KnowledgeCategoryRevision.status
                        == KnowledgeCategoryRevisionStatus.PROCESSING,
                        KnowledgeCategoryRevision.lease_expires_at < now,
                    ),
                ),
            )
            .values(
                status=KnowledgeCategoryRevisionStatus.PROCESSING,
                error_message=None,
                failure_code=None,
                processing_token=claim_token,
                processing_started_at=now,
                lease_expires_at=now + timedelta(seconds=CATEGORY_PROCESSING_LEASE_SECONDS),
                attempt_count=KnowledgeCategoryRevision.attempt_count + 1,
            )
        )
        await self.db.commit()
        if claim.rowcount != 1:
            await self.db.refresh(revision)
            if revision.attempt_count >= MAX_CATEGORY_PROCESSING_ATTEMPTS and revision.status in {
                KnowledgeCategoryRevisionStatus.PROCESSING,
                KnowledgeCategoryRevisionStatus.FAILED,
            }:
                revision.status = KnowledgeCategoryRevisionStatus.FAILED
                revision.failure_code = CATEGORY_RETRY_EXHAUSTED
                revision.error_message = "Category processing retry limit reached"
                revision.lease_expires_at = None
                revision.processing_token = None
                await self.db.commit()
            return
        await self.db.refresh(revision)

        try:
            document = validate_category_payload(
                category.category_key,
                revision.normalized_payload,
            )
            units = _render_units(document)
            embedding_started_at = monotonic()
            vectors = await embedder.batch([unit["content"] for unit in units])
            embedding_duration_ms = round((monotonic() - embedding_started_at) * 1000)
            if len(vectors) != len(units):
                raise RuntimeError("embedding provider returned an incomplete category batch")

            project = await self._locked_project(category.project_id)
            category = await self._locked_category(
                category.project_id,
                KnowledgeCategoryKey(category.category_key),
            )
            await self._validate_active_job_references(category.project_id, document)
            revision = await self.db.get(KnowledgeCategoryRevision, revision_id)
            if revision is None:
                raise NotFoundError("Category revision not found")
            if (
                revision.processing_token != claim_token
                or revision.lease_expires_at is None
                or revision.lease_expires_at <= datetime.now(UTC)
            ):
                await self.db.rollback()
                return
            latest_revision_no = await self.db.scalar(
                select(func.max(KnowledgeCategoryRevision.revision_no)).where(
                    KnowledgeCategoryRevision.category_id == category.id
                )
            )
            if revision.revision_no < int(latest_revision_no or revision.revision_no):
                revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
                revision.processing_started_at = None
                revision.lease_expires_at = None
                revision.processing_token = None
                await self.db.commit()
                return
            old_revision = (
                await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
                if category.active_revision_id
                else None
            )
            knowledge_document = KnowledgeDocument(
                file_name=revision.source_filename,
                source="category_yaml",
                status=KnowledgeStatus.PUBLISHED,
                raw_text=revision.source_yaml,
                metadata_={
                    "schema_version": "category-1.0",
                    "category": category.category_key,
                    "category_revision_id": str(revision.id),
                },
                project_id=category.project_id,
                mime_type="application/yaml",
                stage="PUBLISHED",
                category_revision_id=revision.id,
            )
            self.db.add(knowledge_document)
            await self.db.flush()
            inserted_count = await KnowledgeChunkRepo(self.db).insert_category_revision(
                document_id=knowledge_document.id,
                project_id=category.project_id,
                category_revision_id=revision.id,
                category_key=category.category_key,
                units_with_vectors=list(zip(units, vectors, strict=True)),
            )
            if inserted_count != len(units):
                raise RuntimeError("category chunk insertion count mismatch")
            if project.category_authority_started:
                await self._projection_writer.apply_for_revision(
                    category.project_id, revision, document
                )
            if old_revision is not None:
                old_revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
            category.active_revision_id = revision.id
            category.updated_at = func.now()
            revision.status = KnowledgeCategoryRevisionStatus.ACTIVE
            revision.activated_at = datetime.now(UTC)
            revision.processing_started_at = None
            revision.lease_expires_at = None
            revision.processing_token = None
            revision.failure_code = None
            revision.error_message = None
            revision.quality_result = {
                "record_count": len(units),
                "embedding_count": len(vectors),
                "inserted_chunk_count": inserted_count,
                "projection": (
                    "complete" if project.category_authority_started else "deferred_until_cutover"
                ),
                "reference_check": "passed",
                "normalization_changed": (
                    canonical_category_json(document) != revision.source_yaml
                ),
                "warning_codes": [],
                "error_codes": [],
                "checksum": revision.content_sha256,
                "embedding_duration_ms": embedding_duration_ms,
                "duration_ms": round((monotonic() - started_at) * 1000),
            }
            await record_audit(
                self.db,
                action="activate_project_knowledge_category",
                target_type="knowledge_category_revision",
                target_id=str(revision.id),
                payload={
                    "project_id": str(category.project_id),
                    "category": category.category_key,
                    "record_count": len(units),
                    "embedding_count": len(vectors),
                    "inserted_chunk_count": inserted_count,
                    "duration_ms": revision.quality_result["duration_ms"],
                },
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            failed = await self.db.get(KnowledgeCategoryRevision, revision_id)
            if failed is not None and failed.processing_token == claim_token:
                failed.status = KnowledgeCategoryRevisionStatus.FAILED
                failed.failure_code = CATEGORY_ACTIVATION_FAILURE
                failed.error_message = "Category activation failed"
                failed.processing_started_at = None
                failed.lease_expires_at = None
                failed.processing_token = None
                await self.db.commit()
            raise CategoryActivationError() from None

        await self._repair_caches()

    async def clear(
        self,
        *,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
        actor: User,
    ) -> KnowledgeCategoryRevision:
        await self._require_rag_project(project_id)
        project = await self._locked_project(project_id)
        category = await self._locked_category(project_id, category_key)
        latest = await self.db.scalar(
            select(func.max(KnowledgeCategoryRevision.revision_no)).where(
                KnowledgeCategoryRevision.category_id == category.id
            )
        )
        empty_payload = {
            "schema_version": "1.0",
            "category": category_key.value,
            get_category_definition(category_key).list_field: [],
        }
        empty_document = validate_category_payload(category_key, empty_payload, allow_empty=True)
        cleared = KnowledgeCategoryRevision(
            category_id=category.id,
            revision_no=int(latest or 0) + 1,
            status=KnowledgeCategoryRevisionStatus.CLEARED,
            source_filename=f"{category_key.value}.yaml",
            source_yaml=canonical_category_json(empty_document),
            normalized_payload=empty_payload,
            content_sha256=category_checksum(empty_document),
            created_by=actor.id,
            activated_at=datetime.now(UTC),
        )
        self.db.add(cleared)
        old_revision = (
            await self.db.get(KnowledgeCategoryRevision, category.active_revision_id)
            if category.active_revision_id
            else None
        )
        if old_revision is not None:
            old_revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
        if project.category_authority_started:
            await self._projection_writer.clear(project_id, category_key)
        category.active_revision_id = None
        category.updated_at = func.now()
        await self.db.flush()
        await record_audit(
            self.db,
            action="clear_project_knowledge_category",
            actor_id=actor.id,
            target_type="knowledge_category",
            target_id=str(category.id),
            payload={"project_id": str(project_id), "category": category_key.value},
        )
        await self.db.commit()
        await self.db.refresh(cleared)
        await self._repair_caches()
        return cleared

    async def cutover_category_authority(
        self,
        *,
        project_id: uuid.UUID,
        actor: User,
    ) -> Project:
        await self._require_rag_project(project_id)
        project = await self._locked_project(project_id)
        if project.category_authority_started and project.category_cutover_snapshot:
            await self.db.commit()
            await self._repair_caches()
            return project
        categories = list(
            (
                await self.db.scalars(
                    select(KnowledgeCategory)
                    .where(KnowledgeCategory.project_id == project_id)
                    .order_by(KnowledgeCategory.category_key)
                    .with_for_update()
                )
            ).all()
        )
        missing: list[str] = []
        for category in categories:
            if category.active_revision_id is not None:
                continue
            latest = await self.db.scalar(
                select(KnowledgeCategoryRevision)
                .where(KnowledgeCategoryRevision.category_id == category.id)
                .order_by(KnowledgeCategoryRevision.revision_no.desc())
                .limit(1)
            )
            if latest is None or latest.status is not KnowledgeCategoryRevisionStatus.CLEARED:
                missing.append(category.category_key)
        expected = {definition.key.value for definition in CATEGORY_DEFINITIONS}
        missing.extend(sorted(expected - {category.category_key for category in categories}))
        if missing:
            raise ConflictError(
                "Category cutover is not ready; prepare or explicitly clear: "
                + ", ".join(sorted(set(missing)))
            )
        project.category_cutover_snapshot = {
            "category_authority_started": project.category_authority_started,
            "active_kb_version_id": (
                str(project.active_kb_version_id) if project.active_kb_version_id else None
            ),
            "category_pointers": {
                category.category_key: (
                    str(category.active_revision_id) if category.active_revision_id else None
                )
                for category in categories
            },
            "project_projection": {
                "summary": project.summary,
                "index_card": project.index_card,
                "is_active": project.is_active,
                "discovery_revision": project.discovery_revision,
            },
        }
        await self._projection_writer.rebuild(project_id, categories)
        project.category_authority_started = True
        project.category_cutover_at = datetime.now(UTC)
        await record_audit(
            self.db,
            action="cutover_project_category_authority",
            actor_id=actor.id,
            target_type="project",
            target_id=str(project.id),
            payload={"ready_category_count": len(categories)},
        )
        await self.db.commit()
        await self._repair_caches()
        return project

    async def rollback_category_authority(
        self,
        *,
        project_id: uuid.UUID,
        actor: User,
    ) -> Project:
        await self._require_rag_project(project_id)
        project = await self._locked_project(project_id)
        snapshot = project.category_cutover_snapshot
        if not snapshot:
            raise ConflictError("Project has no category cutover snapshot to restore")
        categories = list(
            (
                await self.db.scalars(
                    select(KnowledgeCategory)
                    .where(KnowledgeCategory.project_id == project_id)
                    .with_for_update()
                )
            ).all()
        )
        snapshot_pointers = snapshot.get("category_pointers") or {}
        for category in categories:
            target_value = snapshot_pointers.get(category.category_key)
            target_id = uuid.UUID(target_value) if target_value else None
            if category.active_revision_id == target_id:
                continue
            if category.active_revision_id is not None:
                current_revision = await self.db.get(
                    KnowledgeCategoryRevision,
                    category.active_revision_id,
                )
                if current_revision is not None:
                    current_revision.status = KnowledgeCategoryRevisionStatus.ARCHIVED
            if target_id is not None:
                target_revision = await self.db.get(KnowledgeCategoryRevision, target_id)
                if target_revision is None or target_revision.category_id != category.id:
                    raise ConflictError("Category rollback snapshot is no longer restorable")
                target_revision.status = KnowledgeCategoryRevisionStatus.ACTIVE
            category.active_revision_id = target_id
            category.updated_at = func.now()
        project.category_authority_started = bool(snapshot["category_authority_started"])
        active_version = snapshot.get("active_kb_version_id")
        project.active_kb_version_id = uuid.UUID(active_version) if active_version else None
        await self._projection_writer.delete_all(project_id)
        project_projection = snapshot.get("project_projection") or {}
        project.summary = project_projection.get("summary")
        project.index_card = project_projection.get("index_card") or {}
        project.is_active = bool(project_projection.get("is_active"))
        project.discovery_revision = int(project_projection.get("discovery_revision") or 0)
        project.category_cutover_at = None
        project.category_cutover_snapshot = None
        await record_audit(
            self.db,
            action="rollback_project_category_authority",
            actor_id=actor.id,
            target_type="project",
            target_id=str(project.id),
            payload={"restored_legacy_authority": not project.category_authority_started},
        )
        await self.db.commit()
        await self._repair_caches()
        return project

    async def _require_rag_project(self, project_id: uuid.UUID) -> Project:
        project = await self.db.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        knowledge_base = (
            await self.db.get(KnowledgeBase, project.knowledge_base_id)
            if project.knowledge_base_id
            else None
        )
        if knowledge_base is None or knowledge_base.mode is not KnowledgeBaseMode.RAG:
            raise ConflictError("This operation is available only for RAG Projects")
        return project

    async def _locked_category(
        self,
        project_id: uuid.UUID,
        category_key: KnowledgeCategoryKey,
    ) -> KnowledgeCategory:
        category = await self.db.scalar(
            select(KnowledgeCategory)
            .where(
                KnowledgeCategory.project_id == project_id,
                KnowledgeCategory.category_key == category_key.value,
            )
            .with_for_update()
        )
        if category is None:
            raise NotFoundError("Knowledge category not found")
        return category

    async def _locked_project(self, project_id: uuid.UUID) -> Project:
        project = await self.db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise NotFoundError("Project not found")
        return project

    async def _repair_caches(self) -> None:
        await self._cache_repairer().repair_knowledge_and_jobs()

    async def _validate_active_job_references(
        self,
        project_id: uuid.UUID,
        document: CategoryDocument,
    ) -> None:
        if document.category is KnowledgeCategoryKey.JOBS:
            new_job_ids = {item.id for item in document.jobs}
            sibling_categories = (
                await self.db.scalars(
                    select(KnowledgeCategory).where(
                        KnowledgeCategory.project_id == project_id,
                        KnowledgeCategory.category_key != KnowledgeCategoryKey.JOBS.value,
                        KnowledgeCategory.active_revision_id.is_not(None),
                    )
                )
            ).all()
            for sibling in sibling_categories:
                revision = await self.db.get(
                    KnowledgeCategoryRevision,
                    sibling.active_revision_id,
                )
                if revision is None:
                    continue
                sibling_document = validate_category_payload(
                    sibling.category_key,
                    revision.normalized_payload,
                )
                validate_job_references(sibling_document, new_job_ids)
            return
        jobs_category = await self.db.scalar(
            select(KnowledgeCategory).where(
                KnowledgeCategory.project_id == project_id,
                KnowledgeCategory.category_key == KnowledgeCategoryKey.JOBS.value,
            )
        )
        known_ids: set[str] = set()
        if jobs_category and jobs_category.active_revision_id:
            revision = await self.db.get(
                KnowledgeCategoryRevision,
                jobs_category.active_revision_id,
            )
            if revision:
                known_ids = {
                    str(item["id"])
                    for item in revision.normalized_payload.get("jobs", [])
                    if isinstance(item, dict) and item.get("id")
                }
        validate_job_references(document, known_ids)


def _render_units(document: CategoryDocument) -> list[dict]:
    definition = get_category_definition(document.category)
    units: list[dict] = []
    for record in getattr(document, definition.list_field):
        payload = record.model_dump(mode="json", exclude_none=True)
        stable_id = str(payload.get("id"))
        # FaqItem carries per-item tags (section / sub-category from the source
        # sheet). Pop them out of the generic field dump so they do not appear
        # as a mid-payload JSON array in arbitrary field order, then re-attach
        # as a deterministic trailing "Tags:" line in the embedder input. The
        # parser already emits tags in a stable order (broad section → specific
        # sub-category); that order is preserved as-is, not re-sorted. Other
        # categories have no ``tags`` field, so the pop is a harmless no-op.
        tags = payload.pop("tags", [])
        content = f"{definition.label_vi}\n" + "\n".join(
            f"{field}: {json.dumps(value, ensure_ascii=False)}"
            for field, value in payload.items()
        )
        if tags:
            content += f"\nTags: {', '.join(tags)}"
        unit = {
            "content": content,
            "source_quote": content,
            "summary": str(payload.get("title") or payload.get("name") or "") or None,
            "questions": [],
            "entities": {"stable_id": stable_id},
            "metadata": {
                "category": document.category.value,
                "stable_id": stable_id,
            },
        }
        if document.category is KnowledgeCategoryKey.JOBS:
            unit["entities"]["job_title"] = payload.get("title")
        if document.category is KnowledgeCategoryKey.FAQ:
            unit["questions"] = [payload["question"], *payload.get("question_variants", [])]
            unit["required_terms"] = payload.get("required_terms", [])
            unit["forbidden_terms"] = payload.get("forbidden_terms", [])
            # Mirror tags into chunk metadata — same chunk_metadata.tags shape
            # canonical.to_unit uses — so a future pgvector metadata-filter
            # consumer can target them. No consumer reads this today.
            unit["metadata"]["chunk_metadata"] = {"tags": tags}
        units.append(unit)
    return units
