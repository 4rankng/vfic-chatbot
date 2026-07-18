"""RQ entry points for deterministic Project RAG-category activation."""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_category_revision(revision_id: uuid.UUID) -> str:
    from app.core.config import INGEST_JOB_TIMEOUT_SECONDS
    from app.workers.utils import enqueue_job

    job = enqueue_job(
        "ingest",
        run_category_revision_job,
        str(revision_id),
        job_timeout=INGEST_JOB_TIMEOUT_SECONDS,
    )
    return str(job.id)


def run_category_revision_job(revision_id: str) -> None:
    from app.workers.async_runner import run_async

    run_async(_run_category_revision_async(revision_id))


async def _run_category_revision_async(revision_id: str, *, _embedder=None) -> None:
    from app.graph.clients import build_embedder
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.knowledge.category_service import KnowledgeCategoryService
    from app.workers._db import worker_session

    async with worker_session() as db:
        embedder = _embedder
        if embedder is None:
            integration = IntegrationSettingsService(db)
            openrouter = await integration.resolve_openrouter()
            embedder = build_embedder(openrouter_api_key=openrouter.api_key)
        try:
            await KnowledgeCategoryService(db).activate_revision(
                uuid.UUID(revision_id),
                embedder,
            )
        except Exception:
            logger.exception("category revision activation failed: %s", revision_id)
            raise
