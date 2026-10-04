"""SQLAlchemy and provider adapter for existing knowledge ingestion behavior."""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.project_knowledge.application.providers import KnowledgeProviderFactory
from app.project_knowledge.domain.canonical import CANONICAL_SCHEMA_VERSIONS
from app.services.integration_settings import IntegrationSettingsService
from app.services.knowledge import KnowledgePipeline
from app.shared.domain.errors import ConflictError

logger = logging.getLogger(__name__)


class SqlAlchemyKnowledgeIngestionAdapter:
    def __init__(
        self,
        db: AsyncSession,
        *,
        providers: KnowledgeProviderFactory,
    ) -> None:
        self._db = db
        self._providers = providers

    async def ingest_document(
        self,
        document_id: object,
        *,
        embedder: Callable[[str], Awaitable[list[float]]] | None = None,
        json_extractor: Callable[[str, str], Awaitable[str]] | None = None,
        processing_token: uuid.UUID | None = None,
    ) -> None:
        from app.services.knowledge.project_training import (
            BatchCategoryEmbedder,
            ProjectTrainingService,
            training_progress,
        )
        from app.services.knowledge.category_plan_grounding import CategoryPlanExtractionError

        document = await self._db.get(KnowledgeDocument, document_id)
        if document is None:
            logger.warning("ingest job: document %s not found", document_id)
            return
        is_training = bool((document.metadata_ or {}).get("project_training"))
        training = ProjectTrainingService(self._db, processing_token=processing_token) if is_training else None
        if training is not None and not await training.claim(document):
            return
        try:
            integration = IntegrationSettingsService(self._db)
            embedding_config = await integration.resolve_embedding()
            resolved_embedder = (
                embedder
                if embedder is not None
                else self._providers.embedder(embedding=embedding_config)
            )
            is_canonical = (document.metadata_ or {}).get(
                "schema_version"
            ) in CANONICAL_SCHEMA_VERSIONS
            resolved_json_extractor: Callable[[str, str], Awaitable[str]]
            if json_extractor is not None:
                resolved_json_extractor = json_extractor
            elif is_canonical:

                async def _canonical_noop(_system: str, _user: str) -> str:
                    raise RuntimeError("canonical ingest should not call MiniMax")

                resolved_json_extractor = _canonical_noop
            else:
                minimax = await integration.resolve_minimax()
                openrouter = await integration.resolve_openrouter()
                resolved_json_extractor = self._providers.json_extractor(
                    minimax_api_key=minimax.api_key,
                    openrouter_api_key=openrouter.api_key,
                )
            if training is not None:
                await training.prepare_plan(document, resolved_json_extractor)
            await KnowledgePipeline(
                self._db,
                resolved_embedder,
                resolved_json_extractor,
            ).run(document)
            if training is not None:
                await training.run(
                    document,
                    BatchCategoryEmbedder(resolved_embedder),
                    llm_json=resolved_json_extractor,
                )
        except Exception as exc:  # noqa: BLE001 - preserve recorded failure behavior
            # A failed SQL operation requires rollback before recording failure.
            await self._db.rollback()
            failed = await self._db.scalar(
                select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
                .with_for_update().execution_options(populate_existing=True)
            )
            if failed is not None and failed.status == KnowledgeStatus.ARCHIVED:
                await self._db.rollback()
                return  # An administrator deliberately withdrew the source.
            if training is not None and failed is not None and (
                (failed.metadata_ or {}).get("project_training", {}).get("processing_token")
                != str(training.processing_token)
            ):
                await self._db.rollback()
                raise
            if failed is not None:
                failed.status = KnowledgeStatus.FAILED
                failed.stage = "FAILED"
                failed.error = "Chưa hoàn tất xử lý kiến thức. Vui lòng thử xử lý lại tệp đã lưu."
                if isinstance(exc, CategoryPlanExtractionError):
                    failed.error = str(exc)
                elif isinstance(exc, ConflictError):
                    failed.error = "Dữ liệu dự án đã thay đổi. Vui lòng tải lại tệp để cập nhật kiến thức theo dữ liệu hiện tại."
                if is_training:
                    training_progress(failed, status="FAILED", error=failed.error)
                    failed.metadata_ = {**(failed.metadata_ or {}), "project_training": {
                        **(failed.metadata_ or {}).get("project_training", {}),
                        "processing_token": None, "lease_expires_at": None,
                    }}
                await self._db.commit()
            logger.error("knowledge training failed document_id=%s cause=%s", document_id, type(exc).__name__)
            if is_training:
                raise

    


__all__ = ["SqlAlchemyKnowledgeIngestionAdapter"]
