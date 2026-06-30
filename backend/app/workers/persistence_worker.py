"""persistence_low RQ worker: candidate extraction after a bot send.

One job performs one LLM extraction and persists both lead_patch and memory_facts.
Job fns are sync (RQ); they asyncio.run the async services.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enqueue_persist_candidate(job: dict) -> None:
    from app.workers.utils import enqueue_job

    enqueue_job("persistence_low", run_persist_candidate_job, job)


def run_persist_candidate_job(job: dict) -> None:
    from app.workers.async_runner import run_async

    run_async(_persist_candidate_async(job))


def _build_extractor():
    """MiniMax extractor for candidate extraction.

    Thin wrapper over the shared factory so candidate extraction reuses the same
    safety-LLM wiring as the chatbot agent.
    """
    from app.graph.factories import build_minimax_extractor

    return build_minimax_extractor()


async def _persist_candidate_async(job: dict) -> None:
    from app.graph.clients import GeminiEmbedder
    from app.services.candidate_extraction import CandidateExtractionService
    from app.workers._db import worker_session

    try:
        async with worker_session() as db:
            await CandidateExtractionService.persist(
                db,
                GeminiEmbedder().batch,
                _build_extractor(),
                job["chat_id"],
                job.get("user_text", ""),
                job.get("bot_output", ""),
            )
    except Exception:
        logger.warning(
            "candidate extraction failed for chat %s; chat turn continues",
            job.get("chat_id"),
            exc_info=True,
        )
