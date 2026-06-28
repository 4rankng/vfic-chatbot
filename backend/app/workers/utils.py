"""Shared RQ enqueue helper (best-effort, non-fatal).

All worker enqueue functions follow the same pattern: try to push a job onto a
named Redis-backed queue, log but never raise on failure. This helper centralises
that logic so callers are one-liners.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enqueue_job(queue_name: str, fn, *args, job_timeout: int | None = None, **kwargs) -> None:
    """Enqueue an RQ job (best-effort, non-fatal — logs but never raises).

    Parameters
    ----------
    queue_name:
        The RQ queue name (``"webhook_high"``, ``"persistence_low"``, ``"ingest"``).
    fn:
        The sync callable that RQ will invoke (e.g. ``run_chat_turn_job``).
    *args, **kwargs:
        Positional/keyword arguments forwarded to the job function.
    job_timeout:
        Optional per-job timeout in seconds ( forwarded to ``Queue.enqueue`` ).
    """
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        Queue(queue_name, connection=get_redis_sync()).enqueue(
            fn, *args, job_timeout=job_timeout, **kwargs
        )
    except Exception as exc:  # noqa: BLE001 — enqueue failure must not break the caller
        logger.error("failed to enqueue %s on queue %s: %s", fn.__name__, queue_name, exc)
