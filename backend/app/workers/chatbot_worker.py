"""RQ worker: enqueue + run chatbot turns on the webhook_high queue."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def enqueue_chat_run(job: dict) -> None:
    """Enqueue a bot turn onto the webhook_high RQ queue (best-effort, non-fatal)."""
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        Queue("webhook_high", connection=get_redis_sync()).enqueue(run_chat_turn_job, job)
    except Exception as exc:  # noqa: BLE001 — enqueue failure must not break the webhook ack
        logger.error("failed to enqueue chat run: %s", exc)


def run_chat_turn_job(job: dict) -> None:
    """RQ job entrypoint (sync). Runs the async graph turn."""
    asyncio.run(_run_job_async(job))


def _enqueue_persist(persist_job: dict) -> None:
    """Fire both lead + memory persistence after a SENT reply (best-effort)."""
    from app.workers.persistence_worker import enqueue_persist_lead, enqueue_persist_memory

    enqueue_persist_lead(persist_job)
    enqueue_persist_memory(persist_job)


async def _run_job_async(job: dict) -> None:
    # Imported lazily so importing this module (e.g. in tests) does NOT pull in the
    # heavy LLM/Google deps — those are only needed for a real run.
    from app.workers._db import worker_session
    from app.graph.factories import build_deps
    from app.graph.runner import BotRunState, run_turn

    state = BotRunState(
        conversation_id=job["conversation_id"],
        version_at_start=int(job["version_at_start"]),
        user_text=job["user_text"],
        user_name=job.get("user_name", ""),
    )
    async with worker_session() as db:
        deps = await build_deps(db)
        deps.persist = _enqueue_persist  # wire lead/memory extraction on SENT
        await run_turn(state, deps)
