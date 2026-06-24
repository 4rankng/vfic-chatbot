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
    """Shared MiniMax extractor (safety model, temp 0) for lead + memory extraction.

    Defined once so the lead and memory paths cannot drift on model/base_url/timeout.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from app.core.config import get_settings

    s = get_settings()
    llm = ChatOpenAI(
        model=s.minimax_safety_model,
        api_key=s.minimax_api_key,
        base_url=s.minimax_base_url,
        temperature=0.0,
    )

    async def extractor(system: str, user: str) -> str:
        return (await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])).content

    return extractor


async def _persist_lead_async(job: dict) -> None:
    from app.core.db import async_session
    from app.services.lead_service import LeadExtractionService

    async with async_session() as db:
        lead = await LeadExtractionService.extract(
            _build_extractor(), job["user_text"], job.get("bot_output", ""), job["chat_id"]
        )
        if lead:
            await LeadExtractionService.upsert(db, lead)


async def _persist_memory_async(job: dict) -> None:
    from app.core.db import async_session
    from app.graph.llm_real import GeminiEmbedder
    from app.services.memory_service import MemoryService

    async with async_session() as db:
        await MemoryService.persist(
            db, GeminiEmbedder(), _build_extractor(),
            job["chat_id"], job["user_text"], job.get("bot_output", ""),
        )
