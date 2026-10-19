"""RQ worker: Cloudfone daily voice-transcript insights tick.

The ``scheduler`` container enqueues ``run_cloudfone_insights_tick`` daily (env
``cloudfone_insights_cron``, default ``0 1 * * *`` = 01:00 UTC = 08:00 Vietnam) onto
the ``maintenance`` queue; ``worker-maintenance`` consumes it. The tick always
reports on the previous full ICT day — no send-state row, so a rerun or a
catch-up after downtime re-delivers the same day's letter instead of skipping
it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_QUIET_STATUSES = {"disabled", "empty"}


def run_cloudfone_insights_tick() -> str:
    """RQ job entrypoint (sync). Returns the run status for the job result."""
    from app.workers.async_runner import run_async

    result = run_async(_tick_async())
    if result.status in _QUIET_STATUSES:
        logger.debug("cloudfone insights tick: %s", result.status)
    elif result.status == "unconfigured":
        logger.warning(
            "cloudfone insights tick: unconfigured (%s)",
            ", ".join(result.missing) or result.error or "no Cloudfone auth credentials",
        )
    else:
        logger.info(
            "cloudfone insights tick: %s calls=%d",
            result.status,
            result.insights_count,
        )
    return result.status


async def _tick_async():
    # The composition root (not the service) builds the LLM callable: services
    # must not import the graph package, mirroring the email digest tick.
    from app.composition.email_digest import build_digest_summarizer_for
    from app.services.cloudfone import run_cloudfone_insights
    from app.workers._db import worker_session

    async with worker_session() as db:
        try:
            summarizer = await build_digest_summarizer_for(db)
        except Exception:  # noqa: BLE001 — the letter still ships, summaries empty
            logger.warning(
                "cloudfone insights tick: summarizer unavailable, sending without",
                exc_info=True,
            )
            summarizer = None
        return await run_cloudfone_insights(db, summarizer=summarizer)
