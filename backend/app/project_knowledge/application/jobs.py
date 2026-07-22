"""Application-owned scheduling contract for project/knowledge background work."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProjectKnowledgeJobKind(StrEnum):
    DOCUMENT_INGEST = "document_ingest"
    VERSION_INGEST = "version_ingest"
    CATEGORY_REVISION = "category_revision"
    EXTERNAL_SOURCE_SYNC = "external_source_sync"
    SINGLE_PAGE_SOURCE_SYNC = "single_page_source_sync"


@dataclass(frozen=True, slots=True)
class ProjectKnowledgeJobRequest:
    kind: ProjectKnowledgeJobKind
    aggregate_id: object
    requested_job_id: str | None = None


class EnqueueReceiptUnknown(RuntimeError):
    """The broker may have accepted the job, but no receipt was confirmed."""


class ProjectKnowledgeJobPort(Protocol):
    def enqueue(self, request: ProjectKnowledgeJobRequest) -> str | None: ...


class ProjectKnowledgeJobs:
    """Use-case facade preserving the distinct receipt contracts of each job family."""

    def __init__(self, port: ProjectKnowledgeJobPort) -> None:
        self._port = port

    def ingest_document(self, document_id: object) -> None:
        self._port.enqueue(
            ProjectKnowledgeJobRequest(
                ProjectKnowledgeJobKind.DOCUMENT_INGEST,
                document_id,
            )
        )

    def ingest_version(self, version_id: object) -> str:
        receipt = self._port.enqueue(
            ProjectKnowledgeJobRequest(
                ProjectKnowledgeJobKind.VERSION_INGEST,
                version_id,
            )
        )
        if receipt is None:
            raise RuntimeError("knowledge version enqueue failed")
        return receipt

    def process_category_revision(self, revision_id: object) -> str:
        receipt = self._port.enqueue(
            ProjectKnowledgeJobRequest(
                ProjectKnowledgeJobKind.CATEGORY_REVISION,
                revision_id,
            )
        )
        if receipt is None:
            raise RuntimeError("category revision enqueue failed")
        return receipt

    def sync_external_source(
        self,
        state_id: object,
        *,
        job_id: str | None = None,
    ) -> str | None:
        return self._port.enqueue(
            ProjectKnowledgeJobRequest(
                ProjectKnowledgeJobKind.EXTERNAL_SOURCE_SYNC,
                state_id,
                requested_job_id=job_id,
            )
        )

    def sync_single_page_source(
        self,
        state_id: object,
        *,
        job_id: str | None = None,
    ) -> str | None:
        return self._port.enqueue(
            ProjectKnowledgeJobRequest(
                ProjectKnowledgeJobKind.SINGLE_PAGE_SOURCE_SYNC,
                state_id,
                requested_job_id=job_id,
            )
        )


__all__ = [
    "EnqueueReceiptUnknown",
    "ProjectKnowledgeJobKind",
    "ProjectKnowledgeJobPort",
    "ProjectKnowledgeJobRequest",
    "ProjectKnowledgeJobs",
]
