"""Shared RQ enqueue helper (best-effort, non-fatal).

All worker enqueue functions follow the same pattern: try to push a job onto a
named Redis-backed queue, log but never raise on failure. This helper centralises
that logic so callers are one-liners.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enqueue_job(
    queue_name: str,
    fn,
    *args,
    job_timeout: int | None = None,
    max_depth: int | None = None,
    **kwargs,
) -> bool:
    """Enqueue an RQ job. Returns False on failure or when queue depth exceeds
    *max_depth* (backpressure — lets callers return 503 so the upstream retries).

    When *max_depth* is ``None`` (the default) the depth check is skipped and the
    behaviour is best-effort (logs but never raises), matching the original contract
    for persistence / followup paths.
    """
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        q = Queue(queue_name, connection=get_redis_sync())
        if max_depth is not None and q.count >= max_depth:
            logger.warning(
                "queue %s depth %d >= max_depth %d, rejecting enqueue",
                queue_name,
                q.count,
                max_depth,
            )
            return False
        q.enqueue(fn, *args, job_timeout=job_timeout, **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 — enqueue failure must not break the caller
        logger.error("failed to enqueue %s on queue %s: %s", fn.__name__, queue_name, exc, exc_info=True)
        return False
