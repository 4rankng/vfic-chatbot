"""SQLAlchemy-backed adapter for category lifecycle use cases."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.project_knowledge.application.jobs import ProjectKnowledgeJobs
from app.project_knowledge.application.cache import ProjectKnowledgeCacheRepairPort
from app.services.knowledge.category_service import KnowledgeCategoryService


class SqlAlchemyCategoryAdapter:
    def __init__(
        self,
        db: AsyncSession,
        *,
        jobs: ProjectKnowledgeJobs,
        cache_repair: ProjectKnowledgeCacheRepairPort,
    ) -> None:
        self._service = KnowledgeCategoryService(
            db,
            jobs=jobs,
            cache_repair=cache_repair,
        )

    async def list_catalog(self, project_id: object) -> Any:
        return await self._service.list_catalog(project_id)

    async def get_active_source(self, project_id: object, category_key: object) -> Any:
        return await self._service.get_active_source(project_id, category_key)

    async def stage_replacement(
        self,
        *,
        project_id: object,
        category_key: object,
        filename: str,
        source_yaml: str,
        actor: object,
    ) -> Any:
        return await self._service.stage_replacement(
            project_id=project_id,
            category_key=category_key,
            filename=filename,
            source_yaml=source_yaml,
            actor=actor,
        )

    async def activate_revision(
        self,
        revision_id: object,
        embedder: object,
        *,
        claim_token: object | None = None,
    ) -> Any:
        return await self._service.activate_revision(
            revision_id,
            embedder,
            claim_token=claim_token,
        )

    async def clear(
        self,
        *,
        project_id: object,
        category_key: object,
        actor: object,
    ) -> Any:
        return await self._service.clear(
            project_id=project_id,
            category_key=category_key,
            actor=actor,
        )

    async def cutover_category_authority(
        self,
        *,
        project_id: object,
        actor: object,
    ) -> Any:
        return await self._service.cutover_category_authority(
            project_id=project_id,
            actor=actor,
        )

    async def rollback_category_authority(
        self,
        *,
        project_id: object,
        actor: object,
    ) -> Any:
        return await self._service.rollback_category_authority(
            project_id=project_id,
            actor=actor,
        )


__all__ = ["SqlAlchemyCategoryAdapter"]
