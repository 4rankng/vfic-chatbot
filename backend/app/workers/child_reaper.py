"""SIGCHLD reaping for long-lived RQ worker processes.

A process that gains a child it never ``wait()``s leaves that child a zombie on
its exit, and zombies accumulate for the life of the parent.  The droplet saw
exactly that on 2026-10-30: ``ps -eo stat | grep Z`` climbed 15 -> 22 -> 29
across the day under the worker containers and only a container recreate
cleared the count.

Neither RQ worker class reaps more than it must:

* ``Worker`` (the fork worker behind bare ``rq worker``) waits for exactly one
  child per job — its work horse (``os.wait4(self.horse_pid, 0)`` in
  ``Worker.wait_for_horse``).  Every other child of the worker process is
  invisible to it and, un-reaped, is a permanent zombie.
* ``SimpleWorker`` (``run_worker``) runs jobs in-process and never waits for
  children at all, so anything that ever dies in its process stays a zombie
  forever.

This module closes the hole with a SIGCHLD handler that reaps dead children as
they die.  All calls are worker-entry plumbing — no job code is affected:

* :func:`install` alone, for the in-process ``SimpleWorker`` path: nothing
  waits for children there, so every dead child is swept the moment it dies.
* :func:`pause` / :func:`resume` around the fork worker's whole horse cycle
  (see :class:`app.workers.reaping_worker.ReapingWorker`): RQ's ``os.wait4``
  must receive the horse's own exit status — that is what its success/failure
  reporting is built on — so sweeping is paused from before the fork until
  after RQ has consumed the horse, and :func:`resume` then sweeps whatever the
  cycle left behind.  If a horse is ever reaped before RQ's ``wait4`` anyway
  (it cannot be through this path, but rq tolerates it): ``wait_for_horse``
  suppresses the resulting ``ChildProcessError`` and ``monitor_work_horse``
  falls through to the job status stored in Redis — a finished job still
  reports success with its result intact.
"""

from __future__ import annotations

import logging
import os
import signal
from types import FrameType

logger = logging.getLogger(__name__)

# While True the reaper defers: RQ's work-horse cycle owns child reaping
# (its os.wait4 consumes the horse) and must never have a status stolen.
_paused = False


def install() -> None:
    """Install the SIGCHLD handler and reap whatever is already dead.

    Idempotent: re-registering the same handler is harmless, so every worker
    entry can call this unconditionally.
    """
    signal.signal(signal.SIGCHLD, _on_sigchld)
    sweep()


def pause() -> None:
    """Defer all reaping — call BEFORE forking the work horse RQ will wait4."""
    global _paused
    _paused = True


def resume() -> None:
    """End the deferral and reap what the paused window left behind."""
    global _paused
    _paused = False
    sweep()


def sweep() -> None:
    """Reap every dead child.  Never blocks; defers while paused."""
    if _paused:
        return
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            # No children at all — nothing left to reap.
            return
        if pid == 0:
            # Children exist but none is dead yet.
            return
        logger.debug("reaped zombie child pid=%d", pid)


def _on_sigchld(_signum: int, _frame: FrameType | None) -> None:
    sweep()
