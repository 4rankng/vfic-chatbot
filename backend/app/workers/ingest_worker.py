"""RQ worker: enqueue + run the knowledge ingest pipeline on the `ingest` queue.

Consumed by the `worker-ingest` service (``rq worker ingest``). Canonical Markdown jobs
use the deterministic parse -> embed -> index path; legacy/freeform jobs use the full
digest (MiniMax/OpenRouter) -> embed (configured provider) -> index path.
Failures are recorded on the document (status=FAILED, error=...) so the UI can surface
them; they never crash the worker.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_ingest(doc_id) -> None:
    """Enqueue a training-pipeline job for one document (best-effort, non-fatal)."""
    from app.core.config import INGEST_JOB_TIMEOUT_SECONDS
    from app.workers.utils import enqueue_job

    enqueue_job(
        "ingest",
        run_ingest_job,
        str(doc_id),
        job_timeout=INGEST_JOB_TIMEOUT_SECONDS,
    )


def enqueue_ingest_version(version_id) -> str:
    """Enqueue a training-pipeline job for one KB version and return the RQ job id."""
    from app.core.config import INGEST_JOB_TIMEOUT_SECONDS
    from app.workers.utils import enqueue_job

    receipt_id = f"knowledge-version-{version_id}"
    job_id = enqueue_job(
        "ingest",
        run_ingest_version_job,
        str(version_id),
        job_timeout=INGEST_JOB_TIMEOUT_SECONDS,
        return_job_id=True,
        job_id=receipt_id,
    )
    if job_id is None:
        raise RuntimeError("knowledge version enqueue failed")
    return job_id


def run_ingest_version_job(version_id: str) -> None:
    """RQ job entrypoint for version-level KB ingest."""
    try:
        from app.workers.async_runner import run_async

        run_async(_run_version_job_async(version_id))
    except Exception as exc:
        logger.exception("ingest job crashed for KB version %s", version_id)
        _mark_version_failed_sync(version_id, exc)
        raise


def run_ingest_job(doc_id: str) -> None:
    """RQ job entrypoint (sync). Runs the async pipeline."""
    try:
        from app.workers.async_runner import run_async

        run_async(_run_job_async(doc_id))
    except Exception as exc:
        # RQ-level failures (notably JobTimeoutException from its death penalty)
        # can be raised outside the coroutine frame, bypassing _run_job_async's
        # document error handler. Record a terminal state with a sync DB write so
        # the admin UI does not sit forever at DIGESTING/PROCESSING.
        logger.exception("ingest job crashed for document %s", doc_id)
        _mark_doc_failed_sync(doc_id, exc)
        raise


async def _run_job_async(doc_id: str, *, _embed=None, _llm=None) -> None:
    # Imported lazily so importing this module (e.g. in tests) does NOT pull in the
    # heavy LLM/Google deps — those are only needed for a real run. ``_embed``/``_llm``
    # are injectable so the cross-loop regression test can run the pipeline with fakes.
    from app.graph.clients import build_embedder
    from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
    from app.services.knowledge.canonical import CANONICAL_SCHEMA_VERSIONS
    from app.services.knowledge import KnowledgePipeline
    from app.workers._db import worker_session

    async with worker_session() as db:
        from app.services.integration_settings import IntegrationSettingsService

        integration_settings = IntegrationSettingsService(db)
        openrouter_config = await integration_settings.resolve_openrouter()
        embed = (
            _embed
            if _embed is not None
            else build_embedder(openrouter_api_key=openrouter_config.api_key)
        )
        doc = await db.get(KnowledgeDocument, uuid.UUID(doc_id))
        if doc is None:
            logger.warning("ingest job: document %s not found", doc_id)
            return
        from sqlalchemy import select

        from app.models.knowledge import KBTextFile

        version_file = await db.scalar(
            select(KBTextFile).where(KBTextFile.document_id == doc.id).limit(1)
        )
        is_canonical = (doc.metadata_ or {}).get("schema_version") in CANONICAL_SCHEMA_VERSIONS
        if _llm is not None:
            llm = _llm
        elif is_canonical:

            async def llm(_system: str, _user: str) -> str:
                raise RuntimeError("canonical ingest should not call MiniMax")
        else:
            from app.graph.factories import make_minimax_llm_json

            minimax_config = await integration_settings.resolve_minimax()
            llm = make_minimax_llm_json(
                minimax_api_key=minimax_config.api_key,
                openrouter_api_key=openrouter_config.api_key,
            )
        try:
            await KnowledgePipeline(db, embed, llm).run(doc)
            if version_file is not None:
                from app.services.knowledge.chunk_repository import KnowledgeChunkRepo

                await KnowledgeChunkRepo(db).attach_doc_chunks_to_file(
                    doc_id=doc.id,
                    kb_version_id=version_file.kb_version_id,
                    file_id=version_file.id,
                    project_id=version_file.project_id,
                    source_text=version_file.normalized_text,
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — record + survive
            logger.exception("ingest pipeline failed for document %s", doc_id)
            doc.status = KnowledgeStatus.FAILED
            doc.stage = "FAILED"
            doc.error = f"{type(exc).__name__}: {exc}"[:1000]
            await db.commit()


async def _run_version_job_async(version_id: str, *, _embed=None, _llm=None) -> None:
    from app.graph.clients import build_embedder
    from app.models.knowledge import KBVersion, KBVersionStatus
    from app.services.knowledge import KnowledgeService
    from app.workers._db import worker_session

    async with worker_session() as db:
        from app.services.integration_settings import IntegrationSettingsService

        integration_settings = IntegrationSettingsService(db)
        openrouter_config = await integration_settings.resolve_openrouter()
        embed = (
            _embed
            if _embed is not None
            else build_embedder(openrouter_api_key=openrouter_config.api_key)
        )
        version = await db.get(KBVersion, uuid.UUID(version_id))
        if version is None:
            logger.warning("ingest job: KB version %s not found", version_id)
            return
        if _llm is not None:
            llm = _llm
        else:
            from app.graph.factories import make_minimax_llm_json

            minimax_config = await integration_settings.resolve_minimax()
            llm = make_minimax_llm_json(
                minimax_api_key=minimax_config.api_key,
                openrouter_api_key=openrouter_config.api_key,
            )
        try:
            await KnowledgeService(db).ingest_version(embed, version, llm_json=llm)
        except Exception as exc:  # noqa: BLE001 — record + survive
            logger.exception("ingest pipeline failed for KB version %s", version_id)
            version.status = KBVersionStatus.FAILED
            version.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            await db.commit()


def _mark_doc_failed_sync(doc_id: str, exc: Exception) -> None:
    """Persist FAILED for crashes raised outside the async job coroutine.

    Delegates to the repository layer so the SQL lives in one place.
    """
    try:
        from app.core.config import get_settings
        from app.services.knowledge.repository import mark_document_failed_sync

        mark_document_failed_sync(
            get_settings().database_url_sync,
            doc_id,
            f"{type(exc).__name__}: {exc}",
        )
    except Exception:  # noqa: BLE001 — do not mask the original RQ failure
        logger.exception("failed to mark ingest document %s as FAILED", doc_id)


def _mark_version_failed_sync(version_id: str, exc: Exception) -> None:
    try:
        from app.core.config import get_settings
        from app.services.knowledge.repository import mark_version_failed_sync

        mark_version_failed_sync(
            get_settings().database_url_sync,
            version_id,
            f"{type(exc).__name__}: {exc}",
        )
    except Exception:  # noqa: BLE001 — do not mask the original RQ failure
        logger.exception("failed to mark KB version %s as FAILED", version_id)
