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

        from app.core.redis import get_redis_sync

        Queue("ingest", connection=get_redis_sync()).enqueue(run_ingest_job, str(doc_id))
    except Exception as exc:  # noqa: BLE001 — enqueue failure must not break the upload response
        logger.error("failed to enqueue ingest job: %s", exc)


def run_ingest_job(doc_id: str) -> None:
    """RQ job entrypoint (sync). Runs the async pipeline."""
    asyncio.run(_run_job_async(doc_id))


async def _run_job_async(doc_id: str) -> None:
    # Imported lazily so importing this module (e.g. in tests) does NOT pull in the
    # heavy LLM/Google deps — those are only needed for a real run.
    from app.core.db import async_session
    from app.graph.llm_real import GeminiEmbedder, make_minimax_llm_json
    from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
    from app.services.knowledge_pipeline import DigestError, KnowledgePipeline

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
