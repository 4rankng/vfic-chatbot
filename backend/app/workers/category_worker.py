"""RQ entry points for deterministic Project RAG-category activation."""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_category_revision(revision_id: uuid.UUID) -> str:
    from app.core.config import INGEST_JOB_TIMEOUT_SECONDS
    from app.workers.utils import enqueue_job

    receipt_id = f"category-revision-{revision_id}"
    job_id = enqueue_job(
        "ingest",
        run_category_revision_job,
        str(revision_id),
        job_timeout=INGEST_JOB_TIMEOUT_SECONDS,
        return_job_id=True,
        job_id=receipt_id,
    )
    if job_id is None:
        raise RuntimeError("category revision enqueue failed")
    return job_id


def run_category_revision_job(revision_id: str) -> None:
    from app.workers.async_runner import run_async

    processing_token = uuid.uuid4()
    try:
        run_async(
            _run_category_revision_async(
                revision_id,
                _claim_token=processing_token,
            )
        )
    except Exception as exc:
        _mark_category_revision_failed_sync(revision_id, processing_token)
        # The stable failure code is what the UI reads, but on its own it hid
        # the cause: a missing settings-page credential surfaced as an
        # unexplained "category_worker_failed". Log the reason, keep the code.
        logger.error(
            "category revision worker failed revision_id=%s "
            "failure_code=category_worker_failed cause=%s: %s",
            revision_id,
            type(exc).__name__,
            exc,
        )
        from app.services.knowledge.category_service import CategoryActivationError

        raise CategoryActivationError("category_worker_failed") from exc


async def _run_category_revision_async(
    revision_id: str,
    *,
    _embedder=None,
    _claim_token: uuid.UUID | None = None,
) -> None:
    from app.composition.project_knowledge import build_knowledge_provider_factory
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.knowledge.category_service import KnowledgeCategoryService
    from app.workers._db import worker_session

    async with worker_session() as db:
        embedder = _embedder
        if embedder is None:
            integration = IntegrationSettingsService(db)
            openrouter = await integration.resolve_openrouter()
            embedder = build_knowledge_provider_factory().embedder(
                openrouter_api_key=openrouter.api_key
            )
        await KnowledgeCategoryService(db).activate_revision(
            uuid.UUID(revision_id),
            embedder,
            claim_token=_claim_token,
        )


def _mark_category_revision_failed_sync(
    revision_id: str,
    processing_token: uuid.UUID,
) -> None:
    try:
        from app.core.config import get_settings
        from app.services.knowledge.document_repository import (
            mark_category_revision_failed_sync,
        )

        mark_category_revision_failed_sync(
            get_settings().database_url_sync,
            revision_id,
            str(processing_token),
            "category_worker_failed",
        )
    except Exception:  # noqa: BLE001 - never mask the stable worker failure
        logger.error(
            "category revision failure marker failed revision_id=%s",
            revision_id,
        )
