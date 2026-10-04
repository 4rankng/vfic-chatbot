"""Shared RQ enqueue helper (best-effort, non-fatal).

All worker enqueue functions follow the same pattern: try to push a job onto a
named Redis-backed queue, log but never raise on failure. This helper centralises
that logic so callers are one-liners.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, overload

if TYPE_CHECKING:
    from rq import Queue

logger = logging.getLogger(__name__)


class EnqueueStatusUnknown(RuntimeError):
    """Raised when Redis cannot confirm whether a named job was accepted."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"enqueue status is unknown for job {job_id}")
        self.job_id = job_id


# Default depth bounds applied when a call site passes no explicit max_depth.
# webhook_high stays out of this map: its call sites pass
# chat_queue_max_depth explicitly (chatbot_worker), and that remains the
# reference pattern. 0 in settings disables a bound, mirroring
# chat_queue_max_depth semantics.
_QUEUE_MAX_DEPTH_SETTINGS_FIELDS = {
    "maintenance": "maintenance_queue_max_depth",
}


def _default_max_depth(queue_name: str) -> int | None:
    field = _QUEUE_MAX_DEPTH_SETTINGS_FIELDS.get(queue_name)
    if field is None:
        return None
    from app.core.config import get_settings

    return getattr(get_settings(), field) or None


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

    When *max_depth* is ``None`` the depth check is skipped for unmanaged queues
    (best-effort, logs but never raises); the queues in
    ``_QUEUE_MAX_DEPTH_SETTINGS_FIELDS`` fall back to their configured default
    bound instead, so every enqueue site for them is backpressured without each
    caller passing a limit explicitly.
    """
    connection = None
    # Bound before the try: the recovery handler below re-submits with these,
    # and an early failure (Redis down, Queue() raising) must NameError-proof
    # it instead of masking the original error.
    q: Queue | None = None
    enqueue_options: dict[str, Any] = {}
    try:
        from rq import Queue

        from app.core.redis import get_redis_sync

        connection = get_redis_sync()
        q = Queue(queue_name, connection=connection)
        if max_depth is None:
            max_depth = _default_max_depth(queue_name)
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
                    if q is None or not enqueue_options:
                        # This attempt failed before a submit was even built;
                        # there is nothing to re-submit with.
                        raise EnqueueStatusUnknown(job_id) from exc
                    q.enqueue(fn, *args, **enqueue_options)
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
