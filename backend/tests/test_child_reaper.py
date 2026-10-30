"""The child reaper must clear zombies and must never steal RQ's work horse.

The 2026-10-30 droplet incident — ``ps -eo stat | grep Z`` climbing 15 -> 22 ->
29 across the day inside the worker containers — is what these tests pin:

1. an un-waited child stays a zombie forever (the bug, so the rest cannot pass
   vacuously),
2. :func:`child_reaper.install` reaps such children, both as they die and as a
   backlog that predates the handler (the fix), and
3. the paused horse cycle keeps the horse's exit status for RQ's own
   ``os.wait4`` while still sweeping non-horse zombies afterwards — stealing
   that status would change fork-worker job reporting, i.e. job behaviour (the
   "fix must not change job behaviour" contract).

Zombie state is observed the portable way: ``ps -o stat=`` reports ``Z`` for a
dead un-reaped child and nothing at all once it is gone (``/proc`` and
``os.waitid`` are Linux-only; these tests run on the macOS dev fleet too).
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest

from app.workers import child_reaper

pytestmark = [
    pytest.mark.skipif(os.name == "nt", reason="forks real child processes"),
    pytest.mark.filterwarnings("ignore:This process .* is multi-threaded.*:DeprecationWarning"),
]


@pytest.fixture(autouse=True)
def restore_sigchld_handler():
    previous = signal.getsignal(signal.SIGCHLD)
    yield
    signal.signal(signal.SIGCHLD, previous)
    child_reaper.resume()  # drop any pause a failed test left behind


def _state(pid: int) -> str | None:
    """The ``ps`` state char of *pid* (``"Z"`` = zombie), or None once reaped."""
    completed = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() or None


def _fork_and_exit(exit_code: int) -> int:
    """Fork a child that dies immediately and return its pid (parent side)."""
    pid = os.fork()
    if pid == 0:
        os._exit(exit_code)
    return pid


def _wait_until_zombie(pid: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        state = _state(pid)
        if (state or "").startswith("Z"):
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"pid {pid} never became a zombie; last state {state!r}")
        time.sleep(0.01)


def _wait_until_gone(pid: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        state = _state(pid)
        if state is None:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"pid {pid} still present as {state!r} — never reaped")
        time.sleep(0.01)


def test_unwaited_children_stay_zombies_without_the_reaper():
    """The bug itself, kept as the non-vacuous guard for the tests below.

    Without a waiter, three forked children are three ``Z`` rows — "nothing
    observed" would otherwise also describe children that never ran at all.
    """
    pids = [_fork_and_exit(0) for _ in range(3)]
    for pid in pids:
        _wait_until_zombie(pid)
    for pid in pids:
        os.waitpid(pid, 0)  # cleanup; the reaper is not installed in this test


def test_install_reaps_children_that_died_before_the_handler():
    """install() sweeps the backlog a worker process accumulated before boot."""
    pids = [_fork_and_exit(0) for _ in range(5)]
    for pid in pids:
        _wait_until_zombie(pid)  # five stat-Z children, counted as the incident did
    child_reaper.install()
    for pid in pids:
        _wait_until_gone(pid)  # zero remain after the sweep


def test_sigchld_reaps_children_as_they_die():
    """With the handler installed, a dying child never becomes a lasting zombie."""
    child_reaper.install()
    pids = [_fork_and_exit(0) for _ in range(5)]
    for pid in pids:
        _wait_until_gone(pid)


def test_paused_horse_cycle_defers_to_rq_wait4_then_sweeps():
    """The job-behaviour contract for the fork worker's horse cycle.

    Paused from before the fork, the reaper must leave the horse's exit status
    to RQ's ``os.wait4`` (``wait_for_horse`` needs the real status of its
    horse), while a non-horse child dying in the same window is deferred, not
    dropped — ``resume()`` sweeps it once the horse is consumed.
    """
    child_reaper.install()
    child_reaper.pause()  # the horse cycle starts before the fork — no race
    horse = _fork_and_exit(17)
    other = _fork_and_exit(0)  # a non-horse child dying inside the same window
    _wait_until_zombie(horse)
    _wait_until_zombie(other)  # the handler deferred both
    pid, status = os.waitpid(horse, 0)  # what rq's wait_for_horse does
    assert pid == horse
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 17
    child_reaper.resume()
    _wait_until_gone(other)  # the deferred zombie is swept now
