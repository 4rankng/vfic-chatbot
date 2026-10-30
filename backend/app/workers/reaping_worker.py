"""RQ fork worker that can never accumulate zombie children.

Bare ``rq worker`` runs :class:`rq.Worker`, which forks a work horse per job
and reaps exactly that horse — every other child of the worker process is
invisible to it, and one that exits un-waited is a permanent zombie (the
2026-10-30 droplet incident: ``ps -eo stat | grep Z`` climbing 15 -> 22 -> 29
across the day in the worker containers).

This class is that worker plus the catch-all reaper from
:mod:`app.workers.child_reaper`, paused across the whole horse cycle so RQ's
own ``os.wait4`` keeps receiving the horse's exit status — job execution and
success/failure reporting are stock RQ.  The ``worker-ingest``,
``worker-category`` and ``worker-maintenance`` services run it via ``rq worker
--worker-class app.workers.reaping_worker.ReapingWorker <queue>`` (see
``docker-compose.yml``); broker resolution from the environment is unchanged.
"""

from __future__ import annotations

from rq import Worker
from rq.job import Job
from rq.queue import Queue

from app.workers import child_reaper


class ReapingWorker(Worker):
    """``rq.Worker`` whose horse cycle never leaves a zombie behind."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        child_reaper.install()

    def execute_job(self, job: Job, queue: Queue) -> None:
        # Paused from before the fork until after RQ's wait4 has consumed the
        # horse, so the reaper can never steal the horse's exit status; every
        # other child that died during the cycle is swept at resume().
        child_reaper.pause()
        try:
            super().execute_job(job, queue)
        finally:
            child_reaper.resume()
