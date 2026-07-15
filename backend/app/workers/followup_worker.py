"""RQ worker: proactive follow-up tick + per-lead follow-up job.

The ``scheduler`` container (``rqscheduler``) periodically enqueues the
``run_proactive_followup_tick`` job onto the ``followup`` queue. ``worker-followup``
`` consumes it and fans out per-lead ``run_followup_job`` jobs (also on ``followup``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def enqueue_followup(conversation_id: str) -> None:
    """Enqueue a per-lead proactive follow-up onto the ``followup`` queue."""
    from app.workers.utils import enqueue_job

    enqueue_job(
        "followup",
        run_followup_job,
        {"conversation_id": conversation_id, "enqueued_at": datetime.now(timezone.utc).isoformat()},
    )


def run_followup_job(job: dict) -> None:
    """RQ job entrypoint (sync). Runs the async proactive turn."""
    from app.workers.async_runner import run_async

    run_async(_run_followup_async(job))


async def _run_followup_async(job: dict) -> None:
    from app.core.config import PROACTIVE_JOB_MAX_AGE_SECONDS

    # Job-age guard: drop stale jobs (e.g. worker was down, now backlogged).
    enqueued_at = job.get("enqueued_at")
    if enqueued_at:
        try:
            enqueued_dt = datetime.fromisoformat(enqueued_at)
        except (ValueError, TypeError):
            enqueued_dt = datetime.now(timezone.utc)
        age = (datetime.now(timezone.utc) - enqueued_dt).total_seconds()
        if age > PROACTIVE_JOB_MAX_AGE_SECONDS:
            logger.info(
                "proactive followup job stale: age=%ds, max=%ds, dropped",
                age,
                PROACTIVE_JOB_MAX_AGE_SECONDS,
            )
            return

    from app.workers._db import worker_session
    from app.graph.factories import build_deps
    from app.graph.proactive import run_proactive_turn

    from sqlalchemy import select

    from app.models.conversation import Conversation

    conversation_id = job["conversation_id"]

    async with worker_session() as db:
        # Fetch the conversation; bail if it vanished or changed.
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv is None:
            logger.info("proactive followup: conversation %s not found, skipping", conversation_id)
            return

        deps = await build_deps(db)
        policy = (
            await deps.runtime_policy.resolve_active_policy()
            if deps.runtime_policy is not None
            else None
        )
        # Proactive outreach is recruitment-specific today: it reads candidate
        # profile state and uses a recruitment prompt. Do not run it for any
        # other active installation until that product owns an equivalent flow.
        if policy is None or policy.pack_key != "recruitment":
            logger.info(
                "proactive followup skipped: installation does not enable recruitment outreach"
            )
            return
        outcome = await run_proactive_turn(conv, deps)
        logger.info(
            "proactive followup complete: conversation=%s outcome=%s",
            conv.zalo_chat_id,
            outcome.get("outcome"),
        )


def run_proactive_followup_tick() -> None:
    """Scheduler tick (sync entrypoint). Scans eligible conversations and enqueues per-lead jobs."""
    from app.workers.async_runner import run_async

    run_async(_run_tick_async())


async def _run_tick_async() -> None:
    from app.workers._db import worker_session
    from app.services.proactive.repository import find_eligible_conversations

    logger.debug("proactive follow-up tick starting")

    async with worker_session() as db:
        candidates = await find_eligible_conversations(db)

    if not candidates:
        logger.debug("proactive follow-up tick: no eligible conversations")
        return

    for conv in candidates:
        enqueue_followup(str(conv.id))

    logger.info("proactive follow-up tick: enqueued %d jobs", len(candidates))
