"""Composition adapter binding project/knowledge job ports to stable RQ facades."""

from __future__ import annotations

from app.project_knowledge.application.jobs import (
    DirectContextIndexRequest,
    EnqueueReceiptUnknown,
    ProjectKnowledgeDirectContextJobs,
    ProjectKnowledgeJobKind,
    ProjectKnowledgeJobRequest,
    ProjectKnowledgeJobs,
)


class WorkerDirectContextIndexAdapter:
    def enqueue(self, request: DirectContextIndexRequest) -> None:
        from app.workers.direct_context_worker import enqueue_direct_context_index

        enqueue_direct_context_index(
            request.knowledge_base_id,
            request.project_id,
            request.text_blob,
        )


class RqProjectKnowledgeJobAdapter:
    def enqueue(self, request: ProjectKnowledgeJobRequest) -> str | None:
        aggregate_id = request.aggregate_id
        try:
            if request.kind is ProjectKnowledgeJobKind.DOCUMENT_INGEST:
                from app.workers.ingest_worker import enqueue_ingest

                enqueue_ingest(aggregate_id)
                return None
            if request.kind is ProjectKnowledgeJobKind.CATEGORY_REVISION:
                from app.workers.category_worker import enqueue_category_revision

                return enqueue_category_revision(aggregate_id)
        except Exception as exc:
            from app.workers.utils import EnqueueStatusUnknown

            if isinstance(exc, EnqueueStatusUnknown):
                raise EnqueueReceiptUnknown from exc
            raise
        raise ValueError(f"unsupported project/knowledge job kind: {request.kind}")


def build_project_knowledge_jobs() -> ProjectKnowledgeJobs:
    return ProjectKnowledgeJobs(RqProjectKnowledgeJobAdapter())


def build_project_knowledge_direct_context_jobs() -> ProjectKnowledgeDirectContextJobs:
    return ProjectKnowledgeDirectContextJobs(WorkerDirectContextIndexAdapter())


__all__ = [
    "RqProjectKnowledgeJobAdapter",
    "WorkerDirectContextIndexAdapter",
    "build_project_knowledge_direct_context_jobs",
    "build_project_knowledge_jobs",
]
