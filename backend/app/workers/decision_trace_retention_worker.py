"""RQ worker: bounded cleanup for expired bot-run decision traces."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

logger = logging.getLogger(__name__)


def run_decision_trace_retention_tick() -> None:
    from app.workers.async_runner import run_async

    run_async(_run_tick_async())


async def _run_tick_async() -> None:
    from app.core.config import get_settings
    from app.models.conversation import BotRun
    from app.workers._db import worker_session

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.decision_trace_retention_days)

    async with worker_session() as db:
        target_ids = (
            await db.scalars(
                select(BotRun.id)
                .where(
                    BotRun.decision_trace.is_not(None),
                    BotRun.ended_at.is_not(None),
                    BotRun.ended_at < cutoff,
                )
                .order_by(BotRun.ended_at.asc(), BotRun.id.asc())
                .limit(settings.decision_trace_retention_batch_size)
            )
        ).all()
        if not target_ids:
            logger.debug("decision trace retention: no expired traces")
            return
        await db.execute(
            update(BotRun)
            .where(BotRun.id.in_(list(target_ids)))
            .values(decision_trace=None)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        logger.info("decision trace retention cleared %d traces", len(target_ids))
