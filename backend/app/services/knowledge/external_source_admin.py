"""Admin CRUD for RAG external knowledge-source sync rows."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.external_source_sync_state import ExternalSourceSyncState
from app.models.user import User
from app.project_knowledge.application.jobs import ProjectKnowledgeJobs
from app.schemas.knowledge import ExternalSourceCreate
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.audit_service import record_audit
from app.shared.domain.errors import ConflictError, NotFoundError
from app.services.knowledge.external_source_sync import (
    ExternalSourceSyncError,
    validate_sheet_url,
)

logger = logging.getLogger(__name__)

RUN_NOW_COOLDOWN_SECONDS = 300


class KnowledgeExternalSourceAdminService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        jobs: ProjectKnowledgeJobs | None = None,
    ) -> None:
        self.db = db
        self._jobs = jobs

    def _job_scheduler(self) -> ProjectKnowledgeJobs:
        if self._jobs is None:
            from app.composition.project_knowledge_jobs import build_project_knowledge_jobs

            self._jobs = build_project_knowledge_jobs()
        return self._jobs

    async def list_sources(self, project_id: uuid.UUID) -> list[ExternalSourceSyncState]:
        rows = (
            (
                await self.db.execute(
                    select(ExternalSourceSyncState)
                    .where(ExternalSourceSyncState.project_id == project_id)
                    .order_by(ExternalSourceSyncState.created_at)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def create_source(
        self,
        project_id: uuid.UUID,
        body: ExternalSourceCreate,
        actor: User,
    ) -> ExternalSourceSyncState:
        try:
            validate_sheet_url(body.sheet_url)
            category_key = KnowledgeCategoryKey(body.category_key.strip().lower()).value
        except ExternalSourceSyncError as exc:
            raise ConflictError(exc.code) from exc
        except ValueError as exc:
            raise ConflictError("invalid_category_key") from exc

        if body.source_kind != "google_sheet":
            raise ConflictError("unsupported_source_kind")

        row = ExternalSourceSyncState(
            project_id=project_id,
            category_key=category_key,
            source_kind=body.source_kind,
            sheet_url=body.sheet_url.strip(),
            sheet_gid=body.sheet_gid,
            auto_sync_enabled=body.auto_sync_enabled,
            created_by=actor.id,
        )
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("external_source_already_exists") from exc

        await record_audit(
            self.db,
            action="external_source_created",
            actor_id=actor.id,
            target_type="external_source_sync_state",
            target_id=str(row.id),
            payload={
                "project_id": str(project_id),
                "category_key": category_key,
                "sheet_url": body.sheet_url,
            },
        )
        await self.db.commit()
        await self.db.refresh(row)
        self._job_scheduler().sync_external_source(row.id)
        return row

    async def run_now(
        self,
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        actor: User,
    ) -> str | None:
        row = await self._require_source(project_id, source_id)
        redis = get_redis()
        cooldown_key = f"ext-src-run-now:{source_id}"
        acquired = await redis.set(cooldown_key, "1", nx=True, ex=RUN_NOW_COOLDOWN_SECONDS)
        if not acquired:
            raise ConflictError("run_now_cooldown")

        job_id = self._job_scheduler().sync_external_source(
            row.id,
            job_id=f"ext-src-sync-{source_id}-{uuid.uuid4().hex}",
        )
        await record_audit(
            self.db,
            action="external_source_run_now",
            actor_id=actor.id,
            target_type="external_source_sync_state",
            target_id=str(source_id),
            payload={"project_id": str(project_id), "category_key": row.category_key, "job_id": job_id},
        )
        await self.db.commit()
        return job_id

    async def delete_source(
        self,
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        actor: User,
    ) -> None:
        row = await self._require_source(project_id, source_id)
        category_key = row.category_key
        await self.db.delete(row)
        await record_audit(
            self.db,
            action="external_source_deleted",
            actor_id=actor.id,
            target_type="external_source_sync_state",
            target_id=str(source_id),
            payload={"project_id": str(project_id), "category_key": category_key},
        )
        await self.db.commit()

    async def _require_source(
        self,
        project_id: uuid.UUID,
        source_id: uuid.UUID,
    ) -> ExternalSourceSyncState:
        row = await self.db.get(ExternalSourceSyncState, source_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("external_source_not_found")
        return row


__all__ = ["KnowledgeExternalSourceAdminService", "RUN_NOW_COOLDOWN_SECONDS"]
