"""persistence_low RQ worker: lead extraction + memory persist (fire-and-forget
after a bot send). Job fns are sync (RQ); they asyncio.run the async services."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def enqueue_persist_lead(job: dict) -> None:
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        Queue("persistence_low", connection=get_redis_sync()).enqueue(run_persist_lead_job, job)
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to enqueue lead persist: %s", exc)


def enqueue_persist_memory(job: dict) -> None:
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        Queue("persistence_low", connection=get_redis_sync()).enqueue(run_persist_memory_job, job)
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to enqueue memory persist: %s", exc)


def run_persist_lead_job(job: dict) -> None:
    asyncio.run(_persist_lead_async(job))


def run_persist_memory_job(job: dict) -> None:
    asyncio.run(_persist_memory_async(job))


def _build_extractor():
    """MiniMax extractor for lead + memory extraction.

    Thin wrapper over the shared factory in llm_real so the lead and memory
    paths reuse the exact same safety-LLM wiring as the chatbot agent.
    """
    from app.graph.factories import build_minimax_extractor

    return build_minimax_extractor()


async def _persist_lead_async(job: dict) -> None:
    from app.workers._db import worker_session
    from app.services.lead_service import LeadExtractionService

    async with worker_session() as db:
        lead = await LeadExtractionService.extract(
            _build_extractor(), job["user_text"], job.get("bot_output", ""), job["chat_id"]
        )
        if lead:
            await LeadExtractionService.upsert(db, lead)


async def _persist_memory_async(job: dict) -> None:
    from app.workers._db import worker_session
    from app.graph.clients import GeminiEmbedder
    from app.services.memory_service import MemoryService

    async with worker_session() as db:
        await MemoryService.persist(
            db, GeminiEmbedder().batch, _build_extractor(),
            job["chat_id"], job["user_text"], job.get("bot_output", ""),
        )
