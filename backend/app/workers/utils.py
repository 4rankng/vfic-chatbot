"""Shared RQ enqueue helper (best-effort, non-fatal).

All worker enqueue functions follow the same pattern: try to push a job onto a
named Redis-backed queue, log but never raise on failure. This helper centralises
that logic so callers are one-liners.
"""

from __future__ import annotations

import logging
from typing import Literal, overload

logger = logging.getLogger(__name__)


class EnqueueStatusUnknown(RuntimeError):
    """Raised when Redis cannot confirm whether a named job was accepted."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"enqueue status is unknown for job {job_id}")
        self.job_id = job_id


@overload
def enqueue_job(
    queue_name: str,
    fn,
    *args,
    job_timeout: int | None = None,
    max_depth: int | None = None,
    return_job_id: Literal[False] = False,
    job_id: str | None = None,
    **kwargs,
) -> bool: ...


@overload
def enqueue_job(
    queue_name: str,
    fn,
    *args,
    job_timeout: int | None = None,
    max_depth: int | None = None,
    return_job_id: Literal[True],
    job_id: str | None = None,
    **kwargs,
) -> str | None: ...


def enqueue_job(
    queue_name: str,
    fn,
    *args,
    job_timeout: int | None = None,
    max_depth: int | None = None,
    return_job_id: bool = False,
    job_id: str | None = None,
    **kwargs,
) -> bool | str | None:
    """Enqueue an RQ job and optionally return its stable identifier.

    Boolean callers receive ``True`` on success and ``False`` on failure or
    backpressure. Callers that set ``return_job_id=True`` receive the RQ job ID
    on success and ``None`` on failure.

    When *max_depth* is ``None`` (the default) the depth check is skipped and the
    behaviour is best-effort (logs but never raises), matching the original contract
    for persistence / followup paths.
    """
    connection = None
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        connection = get_redis_sync()
        q = Queue(queue_name, connection=connection)
        if max_depth is not None and q.count >= max_depth:
            logger.warning(
                "queue %s depth %d >= max_depth %d, rejecting enqueue",
                queue_name,
                q.count,
                max_depth,
            )
            return None if return_job_id else False
        enqueue_options = {"job_timeout": job_timeout, **kwargs}
        if job_id is not None:
            enqueue_options.update(job_id=job_id, unique=True)
        job = q.enqueue(fn, *args, **enqueue_options)
        return str(job.id) if return_job_id else True
    except Exception as exc:  # noqa: BLE001 — enqueue failure must not break the caller
        if return_job_id and job_id is not None and connection is not None:
            try:
                from rq.job import Job

                existing_job = Job.fetch(job_id, connection=connection)
                job_status = existing_job.get_status()
                status = getattr(job_status, "value", job_status)
                if status in {"failed", "stopped"}:
                    existing_job.requeue()
                elif status == "canceled":
                    existing_job.delete()
                    retry_submit = q.enqueue
                    retry_submit(fn, *args, **enqueue_options)
            except Exception as receipt_exc:  # noqa: BLE001 - receipt transport may also fail
                from rq.exceptions import NoSuchJobError

                if not isinstance(receipt_exc, NoSuchJobError):
                    raise EnqueueStatusUnknown(job_id) from exc
            else:
                return job_id
        logger.error(
            "failed to enqueue %s on queue %s: %s", fn.__name__, queue_name, exc, exc_info=True
        )
        return None if return_job_id else False
