"""RQ worker: enqueue + run the knowledge ingest pipeline on the `ingest` queue.

Consumed by the `worker-ingest` service (``rq worker ingest``). Canonical Markdown jobs
use the deterministic parse -> embed -> index path; legacy/freeform jobs use the full
digest (MiniMax) -> embed (Gemini) -> index path.
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
    from app.graph.clients import GeminiEmbedder
    from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
    from app.services.knowledge.canonical import CANONICAL_SCHEMA_VERSIONS
    from app.services.knowledge import KnowledgePipeline
    from app.workers._db import worker_session

    embed = _embed if _embed is not None else GeminiEmbedder()
    async with worker_session() as db:
        doc = await db.get(KnowledgeDocument, uuid.UUID(doc_id))
        if doc is None:
            logger.warning("ingest job: document %s not found", doc_id)
            return
        is_canonical = (doc.metadata_ or {}).get("schema_version") in CANONICAL_SCHEMA_VERSIONS
        if _llm is not None:
            llm = _llm
        elif is_canonical:
            async def llm(_system: str, _user: str) -> str:
                raise RuntimeError("canonical ingest should not call MiniMax")
        else:
            from app.graph.factories import make_minimax_llm_json

            llm = make_minimax_llm_json()
        try:
            await KnowledgePipeline(db, embed, llm).run(doc)
        except Exception as exc:  # noqa: BLE001 — record + survive
            logger.exception("ingest pipeline failed for document %s", doc_id)
            doc.status = KnowledgeStatus.FAILED
            doc.stage = "FAILED"
            doc.error = f"{type(exc).__name__}: {exc}"[:1000]
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
