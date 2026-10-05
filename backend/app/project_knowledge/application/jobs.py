"""Application-owned scheduling contract for project/knowledge background work."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProjectKnowledgeJobKind(StrEnum):
    DOCUMENT_INGEST = "document_ingest"
    CATEGORY_REVISION = "category_revision"


@dataclass(frozen=True, slots=True)
class ProjectKnowledgeJobRequest:
    kind: ProjectKnowledgeJobKind
    aggregate_id: uuid.UUID
    requested_job_id: str | None = None


class EnqueueReceiptUnknown(RuntimeError):
    """The broker may have accepted the job, but no receipt was confirmed."""


class ProjectKnowledgeJobPort(Protocol):
    def enqueue(self, request: ProjectKnowledgeJobRequest) -> str | None: ...


class ProjectKnowledgeJobs:
    """Use-case facade preserving the distinct receipt contracts of each job family."""

    def __init__(self, port: ProjectKnowledgeJobPort) -> None:
        self._port = port

    def ingest_document(self, document_id: uuid.UUID) -> None:
        self._port.enqueue(
            ProjectKnowledgeJobRequest(
                ProjectKnowledgeJobKind.DOCUMENT_INGEST,
                document_id,
            )
        )

    def process_category_revision(self, revision_id: uuid.UUID) -> str:
        receipt = self._port.enqueue(
            ProjectKnowledgeJobRequest(
                ProjectKnowledgeJobKind.CATEGORY_REVISION,
                revision_id,
            )
        )
        if receipt is None:
            raise RuntimeError("category revision enqueue failed")
        return receipt


@dataclass(frozen=True, slots=True)
class DirectContextIndexRequest:
    knowledge_base_id: uuid.UUID
    project_id: uuid.UUID
    text_blob: str


class DirectContextIndexPort(Protocol):
    def enqueue(self, request: DirectContextIndexRequest) -> None: ...


class ProjectKnowledgeDirectContextJobs:
    """Application facade for best-effort DIRECT_CONTEXT re-indexing."""

    def __init__(self, port: DirectContextIndexPort) -> None:
        self._port = port

    def index_direct_context(
        self,
        knowledge_base_id: uuid.UUID,
        project_id: uuid.UUID,
        text_blob: str,
    ) -> None:
        self._port.enqueue(
            DirectContextIndexRequest(
                knowledge_base_id=knowledge_base_id,
                project_id=project_id,
                text_blob=text_blob,
            )
        )


__all__ = [
    "DirectContextIndexPort",
    "DirectContextIndexRequest",
    "EnqueueReceiptUnknown",
    "ProjectKnowledgeDirectContextJobs",
    "ProjectKnowledgeJobKind",
    "ProjectKnowledgeJobPort",
    "ProjectKnowledgeJobRequest",
    "ProjectKnowledgeJobs",
]
