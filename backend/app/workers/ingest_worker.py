"""RQ worker: enqueue + run the LLM training pipeline on the `ingest` queue.

Consumed by the `worker-ingest` service (``rq worker ingest``). Each job runs the full
KnowledgePipeline for one document: digest (MiniMax) -> embed (Gemini) -> index.
Failures are recorded on the document (status=FAILED, error=...) so the UI can surface
them; they never crash the worker.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_ingest(doc_id) -> None:
    """Enqueue a training-pipeline job for one document (best-effort, non-fatal)."""
    try:
        from rq import Queue

        from app.core.config import get_settings
        from app.core.redis import get_redis_sync

        Queue("ingest", connection=get_redis_sync()).enqueue(
            run_ingest_job,
            str(doc_id),
            job_timeout=get_settings().ingest_job_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — enqueue failure must not break the upload response
        logger.error("failed to enqueue ingest job: %s", exc)


def run_ingest_job(doc_id: str) -> None:
    """RQ job entrypoint (sync). Runs the async pipeline."""
    try:
        asyncio.run(_run_job_async(doc_id))
    except Exception as exc:
        # RQ-level failures (notably JobTimeoutException from its death penalty)
        # can be raised outside the coroutine frame, bypassing _run_job_async's
        # document error handler. Record a terminal state with a sync DB write so
        # the admin UI does not sit forever at DIGESTING/PROCESSING.
        logger.exception("ingest job crashed for document %s", doc_id)
        _mark_doc_failed_sync(doc_id, exc)
        raise
    finally:
        _dispose_async_engine_best_effort()


async def _run_job_async(doc_id: str) -> None:
    # Imported lazily so importing this module (e.g. in tests) does NOT pull in the
    # heavy LLM/Google deps — those are only needed for a real run.
    from app.core.db import async_session
    from app.graph.clients import GeminiEmbedder
    from app.graph.factories import make_minimax_llm_json
    from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
    from app.services.knowledge import DigestError, KnowledgePipeline

    try:
        async with async_session() as db:
            doc = await db.get(KnowledgeDocument, uuid.UUID(doc_id))
            if doc is None:
                logger.warning("ingest job: document %s not found", doc_id)
                return
            try:
                pipeline = KnowledgePipeline(db, GeminiEmbedder(), make_minimax_llm_json())
                await pipeline.run(doc)
            except (DigestError, Exception) as exc:  # noqa: BLE001 — record + survive
                logger.exception("ingest pipeline failed for document %s", doc_id)
                doc.status = KnowledgeStatus.FAILED
                doc.stage = "FAILED"
                doc.error = f"{type(exc).__name__}: {exc}"[:1000]
                await db.commit()
    finally:
        await _dispose_async_engine()


def _mark_doc_failed_sync(doc_id: str, exc: Exception) -> None:
    """Persist FAILED for crashes raised outside the async job coroutine."""
    try:
        from sqlalchemy import create_engine, text

        from app.core.config import get_settings

        engine = create_engine(get_settings().database_url_sync, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE knowledge_documents "
                        "SET status = 'FAILED', stage = 'FAILED', "
                        "error = :error, updated_at = now() "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": doc_id, "error": f"{type(exc).__name__}: {exc}"[:1000]},
                )
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 — do not mask the original RQ failure
        logger.exception("failed to mark ingest document %s as FAILED", doc_id)


def _dispose_async_engine_best_effort() -> None:
    try:
        asyncio.run(_dispose_async_engine())
    except Exception:  # noqa: BLE001 — cleanup must not mask the original outcome
        logger.debug("failed to dispose async DB engine after ingest job", exc_info=True)


async def _dispose_async_engine() -> None:
    """Close pooled asyncpg connections before RQ starts a fresh asyncio.run loop."""
    from app.core.db import engine

    await engine.dispose()
