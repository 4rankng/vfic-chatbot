"""RQ worker: index DIRECT_CONTEXT KB text into ``knowledge_chunks`` on the `ingest` queue.

Mirrors :mod:`app.workers.ingest_worker` — sync entrypoint for RQ, async body via
:func:`app.workers.async_runner.run_async`. Failures are logged and non-fatal to the
publish path (the DIRECT_CONTEXT blob is already persisted; indexing is retryable).
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_direct_context_index(
    knowledge_base_id: uuid.UUID,
    project_id: uuid.UUID,
    text_blob: str,
) -> None:
    """Enqueue a DIRECT_CONTEXT indexing job (best-effort, non-fatal).

    Swallows enqueue errors so a Redis hiccup never rolls back the publish txn.
    """
    from app.core.config import INGEST_JOB_TIMEOUT_SECONDS
    from app.workers.utils import enqueue_job

    try:
        enqueue_job(
            "ingest",
            run_direct_context_index_job,
            str(knowledge_base_id),
            str(project_id),
            text_blob,
            job_timeout=INGEST_JOB_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 — enqueue is best-effort
        logger.exception(
            "direct_context index enqueue failed for kb=%s (publish unaffected)",
            knowledge_base_id,
        )


def run_direct_context_index_job(
    knowledge_base_id: str, project_id: str, text_blob: str
) -> None:
    """RQ job entrypoint (sync). Runs the async indexing coroutine."""
    try:
        from app.workers.async_runner import run_async

        run_async(_run_index_async(knowledge_base_id, project_id, text_blob))
    except Exception:  # noqa: BLE001 — never crash the worker
        logger.exception(
            "direct_context indexing crashed for kb=%s", knowledge_base_id
        )
        raise


async def _run_index_async(
    knowledge_base_id: str,
    project_id: str,
    text_blob: str,
    *,
    _embed=None,
    _llm=None,
) -> None:
    """Resolve provider credentials, then delegate to the indexing service.

    ``_embed`` / ``_llm`` are injectable so tests can run the path with fakes.
    """
    from app.graph.clients import build_embedder
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.knowledge.direct_context_indexing import index_direct_context
    from app.workers._db import worker_session

    async with worker_session() as db:
        integration_settings = IntegrationSettingsService(db)
        embedding_config = await integration_settings.resolve_embedding()
        embed = (
            _embed
            if _embed is not None
            else build_embedder(
                provider=embedding_config.provider,
                openrouter_api_key=embedding_config.openrouter_api_key,
                gemini_api_key=embedding_config.gemini_api_key,
            )
        )
        if _llm is not None:
            llm_json = _llm
        else:
            from app.graph.factories import make_minimax_llm_json

            minimax_config = await integration_settings.resolve_minimax()
            openrouter_config = await integration_settings.resolve_openrouter()
            llm_json = make_minimax_llm_json(
                minimax_api_key=minimax_config.api_key,
                openrouter_api_key=openrouter_config.api_key,
            )
        try:
            await index_direct_context(
                db,
                uuid.UUID(knowledge_base_id),
                uuid.UUID(project_id),
                text_blob,
                embedder=embed,
                llm_json=llm_json,
            )
        except Exception:  # noqa: BLE001 — record + survive
            logger.exception(
                "direct_context indexing failed for kb=%s", knowledge_base_id
            )
