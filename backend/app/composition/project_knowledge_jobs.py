"""Composition adapter binding project/knowledge job ports to stable RQ facades."""

from __future__ import annotations

from app.project_knowledge.application.jobs import (
    EnqueueReceiptUnknown,
    ProjectKnowledgeJobKind,
    ProjectKnowledgeJobRequest,
    ProjectKnowledgeJobs,
)


class RqProjectKnowledgeJobAdapter:
    def enqueue(self, request: ProjectKnowledgeJobRequest) -> str | None:
        aggregate_id = request.aggregate_id
        try:
            if request.kind is ProjectKnowledgeJobKind.DOCUMENT_INGEST:
                from app.workers.ingest_worker import enqueue_ingest

                enqueue_ingest(aggregate_id)
                return None
            if request.kind is ProjectKnowledgeJobKind.VERSION_INGEST:
                from app.workers.ingest_worker import enqueue_ingest_version

                return enqueue_ingest_version(aggregate_id)
            if request.kind is ProjectKnowledgeJobKind.CATEGORY_REVISION:
                from app.workers.category_worker import enqueue_category_revision

                return enqueue_category_revision(aggregate_id)
            if request.kind is ProjectKnowledgeJobKind.EXTERNAL_SOURCE_SYNC:
                from app.workers.external_source_sync_worker import enqueue_one_shot

                return enqueue_one_shot(
                    aggregate_id,
                    job_id=request.requested_job_id,
                )
            if request.kind is ProjectKnowledgeJobKind.SINGLE_PAGE_SOURCE_SYNC:
                from app.workers.single_page_external_source_sync_worker import enqueue_one_shot

                return enqueue_one_shot(
                    aggregate_id,
                    job_id=request.requested_job_id,
                )
        except Exception as exc:
            from app.workers.utils import EnqueueStatusUnknown

            if isinstance(exc, EnqueueStatusUnknown):
                raise EnqueueReceiptUnknown from exc
            raise
        raise ValueError(f"unsupported project/knowledge job kind: {request.kind}")


def build_project_knowledge_jobs() -> ProjectKnowledgeJobs:
    return ProjectKnowledgeJobs(RqProjectKnowledgeJobAdapter())


__all__ = ["RqProjectKnowledgeJobAdapter", "build_project_knowledge_jobs"]

