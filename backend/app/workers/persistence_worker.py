"""persistence_low RQ worker: lead extraction + memory persist (fire-and-forget
after a bot send). Job fns are sync (RQ); they asyncio.run the async services."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def enqueue_persist_lead(job: dict) -> None:
    from app.workers.utils import enqueue_job

    enqueue_job("persistence_low", run_persist_lead_job, job)


def enqueue_persist_memory(job: dict) -> None:
    from app.workers.utils import enqueue_job

    enqueue_job("persistence_low", run_persist_memory_job, job)


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
    from app.services.memory_service import greeting_gate
    from app.services.lead_service import LeadExtractionService

    user_text = job.get("user_text", "")
    if not greeting_gate(user_text):
        logger.debug("lead extraction skipped by greeting_gate: '%s'", user_text[:80])
        return

    from app.workers._db import worker_session

    try:
        async with worker_session() as db:
            lead = await LeadExtractionService.extract(
                _build_extractor(), user_text, job.get("bot_output", ""), job["chat_id"]
            )
            if lead:
                await LeadExtractionService.upsert(db, lead)
    except Exception:
        logger.warning(
            "lead extraction failed for chat %s; chat turn continues",
            job.get("chat_id"),
            exc_info=True,
        )


async def _persist_memory_async(job: dict) -> None:
    from app.workers._db import worker_session
    from app.graph.clients import GeminiEmbedder
    from app.services.memory_service import MemoryService

    async with worker_session() as db:
        await MemoryService.persist(
            db, GeminiEmbedder().batch, _build_extractor(),
            job["chat_id"], job["user_text"], job.get("bot_output", ""),
        )
