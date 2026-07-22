"""Application entry points for durable knowledge ingestion jobs."""

from __future__ import annotations

from typing import Protocol


class KnowledgeIngestionPort(Protocol):
    async def ingest_document(
        self,
        document_id: object,
        *,
        embedder: object | None = None,
        json_extractor: object | None = None,
    ) -> None: ...

    async def ingest_version(
        self,
        version_id: object,
        *,
        embedder: object | None = None,
        json_extractor: object | None = None,
    ) -> None: ...


class KnowledgeIngestionUseCases:
    def __init__(self, port: KnowledgeIngestionPort) -> None:
        self._port = port

    async def ingest_document(
        self,
        document_id: object,
        *,
        embedder: object | None = None,
        json_extractor: object | None = None,
    ) -> None:
        await self._port.ingest_document(
            document_id,
            embedder=embedder,
            json_extractor=json_extractor,
        )

    async def ingest_version(
        self,
        version_id: object,
        *,
        embedder: object | None = None,
        json_extractor: object | None = None,
    ) -> None:
        await self._port.ingest_version(
            version_id,
            embedder=embedder,
            json_extractor=json_extractor,
        )


__all__ = ["KnowledgeIngestionPort", "KnowledgeIngestionUseCases"]

