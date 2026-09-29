"""SQLAlchemy and provider adapter for existing knowledge ingestion behavior."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KBTextFile,
    KBVersion,
    KBVersionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.project_knowledge.application.providers import KnowledgeProviderFactory
from app.project_knowledge.domain.canonical import CANONICAL_SCHEMA_VERSIONS
from app.services.integration_settings import IntegrationSettingsService
from app.services.knowledge import KnowledgePipeline, KnowledgeService
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo

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
    ) -> None:
        integration = IntegrationSettingsService(self._db)
        embedding_config = await integration.resolve_embedding()
        resolved_embedder = (
            embedder
            if embedder is not None
            else self._providers.embedder(embedding=embedding_config)
        )
        document = await self._db.get(KnowledgeDocument, document_id)
        if document is None:
            logger.warning("ingest job: document %s not found", document_id)
            return
        version_file = await self._db.scalar(
            select(KBTextFile).where(KBTextFile.document_id == document.id).limit(1)
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
        try:
            await KnowledgePipeline(
                self._db,
                resolved_embedder,
                resolved_json_extractor,
            ).run(document)
            if version_file is not None:
                await KnowledgeChunkRepo(self._db).attach_doc_chunks_to_file(
                    doc_id=document.id,
                    kb_version_id=version_file.kb_version_id,
                    file_id=version_file.id,
                    project_id=version_file.project_id,
                    source_text=version_file.normalized_text,
                )
                await self._db.commit()
        except Exception as exc:  # noqa: BLE001 - preserve recorded failure behavior
            logger.exception("ingest pipeline failed for document %s", document_id)
            document.status = KnowledgeStatus.FAILED
            document.stage = "FAILED"
            document.error = f"{type(exc).__name__}: {exc}"[:1000]
            await self._db.commit()

    async def ingest_version(
        self,
        version_id: object,
        *,
        embedder: Callable[[str], Awaitable[list[float]]] | None = None,
        json_extractor: Callable[[str, str], Awaitable[str]] | None = None,
    ) -> None:
        integration = IntegrationSettingsService(self._db)
        embedding_config = await integration.resolve_embedding()
        resolved_embedder = (
            embedder
            if embedder is not None
            else self._providers.embedder(embedding=embedding_config)
        )
        version = await self._db.get(KBVersion, version_id)
        if version is None:
            logger.warning("ingest job: KB version %s not found", version_id)
            return
        if json_extractor is not None:
            resolved_json_extractor = json_extractor
        else:
            minimax = await integration.resolve_minimax()
            openrouter = await integration.resolve_openrouter()
            resolved_json_extractor = self._providers.json_extractor(
                minimax_api_key=minimax.api_key,
                openrouter_api_key=openrouter.api_key,
            )
        try:
            await KnowledgeService(self._db).ingest_version(
                resolved_embedder,
                version,
                llm_json=resolved_json_extractor,
            )
        except Exception as exc:  # noqa: BLE001 - preserve recorded failure behavior
            logger.exception("ingest pipeline failed for KB version %s", version_id)
            version.status = KBVersionStatus.FAILED
            version.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            await self._db.commit()


__all__ = ["SqlAlchemyKnowledgeIngestionAdapter"]
