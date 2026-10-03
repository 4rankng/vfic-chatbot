"""RQ worker: candidate email digest tick.

The ``scheduler`` container enqueues ``run_email_digest_tick`` hourly (env
``email_digest_tick_cron``, default ``8 * * * *`` = :08 past every hour UTC)
onto the ``maintenance`` queue; ``worker-maintenance`` consumes it. The tick
self-checks due-ness against the ADMIN-EDITABLE schedule stored in
integration_settings (daily/weekly + ICT ``HH:MM``), so a mid-day schedule
flip takes effect at the next tick without re-registering the cron job. A
catch-up send covers a scheduled moment missed while the worker was down.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_QUIET_STATUSES = {"not_due", "disabled", "empty"}


def run_email_digest_tick() -> str:
    """RQ job entrypoint (sync). Returns the run status for the job result."""
    from app.workers.async_runner import run_async

    result = run_async(_tick_async())
    if result.status in _QUIET_STATUSES:
        logger.debug("email digest tick: %s", result.status)
    elif result.status == "unconfigured":
        logger.warning("email digest tick: recipients set but no Resend API key")
    else:
        logger.info("email digest tick: %s candidates=%d", result.status, result.candidate_count)
    return result.status


async def _tick_async():
    from app.services.email_digest.service import run_digest
    from app.workers._db import worker_session

    async with worker_session() as db:
        return await run_digest(db)
