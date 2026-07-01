"""Idempotent rq-scheduler tick registration.

rq-scheduler assigns a random id when ``schedule()`` is called without an
explicit ``id``, so calling it on every web-container boot stacks a NEW
recurring job each time. The scheduled set grew to ~12 copies per tick and
every copy fired on its own interval, over-running both ticks ~12x.

``register_unique_tick`` cancels every existing schedule that targets ``func``
(clears the legacy random-id duplicates), then registers a single job with a
STABLE id so later boots re-score the same sorted-set member instead of
appending another.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def register_unique_tick(scheduler, func, interval: int) -> None:
    """Register exactly one repeatable rq-scheduler job for *func*."""
    func_name = f"{func.__module__}.{func.__name__}"
    # Best-effort cleanup of prior duplicates; failure must not block (re)register.
    try:
        for job in scheduler.get_jobs():  # all scheduled jobs, regardless of time
            if getattr(job, "func_name", None) == func_name:
                scheduler.cancel(job)
    except Exception:  # noqa: BLE001
        log.exception("scheduler dedupe scan failed for %s (non-fatal)", func_name)
    scheduler.schedule(
        scheduled_time=datetime.now(timezone.utc),
        func=func,
        interval=interval,
        repeat=None,
        id=f"vfic-tick-{func.__name__}",
    )
