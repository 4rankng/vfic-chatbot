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

import importlib.util
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _module_exists(module_name: str) -> bool:
    """Whether *module_name* imports (find_spec; parent packages stay imported)."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def purge_dead_ticks(scheduler) -> int:
    """Cancel scheduled jobs whose worker module no longer exists.

    Removed features leave their rq-scheduler entries behind — Redis outlives
    the code that registered it, and ``register_unique_tick`` only dedupes a
    tick's OWN entries, so nothing ever cleaned up after a removal (prod
    2026-10: four phantom entries — external_source_sync ×2, proactive_followup,
    decision_trace_retention — each firing ``AttributeError`` into
    worker-maintenance every interval). Deadness is decided by module
    importability rather than a hardcoded list, so any future removal is swept
    on the next boot too.

    Returns the number of entries cancelled. Best-effort: a scan failure is
    logged and returns 0 — it must never block tick registration.
    """
    try:
        jobs = scheduler.get_jobs()
    except Exception:  # noqa: BLE001 — cleanup must not block registration
        log.exception("scheduler dead-tick scan failed (non-fatal)")
        return 0
    purged = 0
    for job in jobs:
        func_name = getattr(job, "func_name", None) or ""
        module_name = func_name.rsplit(".", 1)[0]
        # Only touch our own workers' ticks ("app.workers.*"); anything else
        # in the scheduled set belongs to another operator/tool.
        if not module_name.startswith("app.workers."):
            continue
        if not _module_exists(module_name):
            try:
                scheduler.cancel(job)
                purged += 1
                log.warning(
                    "purged dead rq-scheduler entry func=%s (module removed)", func_name
                )
            except Exception:  # noqa: BLE001 — one bad entry must not stop the rest
                log.exception("failed to cancel dead scheduler entry func=%s", func_name)
    return purged


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


def register_unique_cron_tick(
    scheduler, func, cron_string: str, *, job_timeout_seconds: int | None = None
) -> None:
    """Register exactly one cron-based rq-scheduler job for *func*.

    Mirror of :func:`register_unique_tick` but for wall-clock-pinned schedules.
    Unlike the interval variant, the next fire is the next cron match — a
    mid-day web-container restart no longer pushes the next run out by a full
    interval. ``cron_string`` is a 5-field cron expression evaluated in UTC
    (rq-scheduler parses with python-crontab); e.g. ``"0 20 * * *"`` = 03:00
    ICT daily. UTC depends on the container TZ being unset/UTC — re-express
    the cron in local time or pin TZ=UTC if the container ever sets one.

    ``job_timeout_seconds`` overrides RQ's 180s default death penalty, which is
    shorter than a real run of some ticks (the email digest summarizes every
    candidate through the LLM before sending) and silently killed the
    2026-10-10 digest mid-enrichment. Left unset, the job keeps the default.
    """
    func_name = f"{func.__module__}.{func.__name__}"
    # Best-effort cleanup of prior duplicates; failure must not block (re)register.
    try:
        for job in scheduler.get_jobs():  # all scheduled jobs, regardless of time
            if getattr(job, "func_name", None) == func_name:
                scheduler.cancel(job)
    except Exception:  # noqa: BLE001
        log.exception("scheduler dedupe scan failed for %s (non-fatal)", func_name)
    # The Scheduler instance is already bound to a queue at construction (see
    # app.main lifespan); cron() inherits it, matching the interval path.
    scheduler.cron(
        cron_string,
        func=func,
        repeat=None,
        id=f"vfic-tick-{func.__name__}",
        **({"timeout": job_timeout_seconds} if job_timeout_seconds else {}),
    )
