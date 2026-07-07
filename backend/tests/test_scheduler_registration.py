"""Tests for register_unique_tick — mock-based, no Redis/DB required."""

from unittest.mock import MagicMock

from app.workers.scheduler_utils import register_unique_tick


def _make_job(func_name: str) -> MagicMock:
    j = MagicMock()
    j.func_name = func_name
    return j


def test_cancels_matching_jobs_and_keeps_unrelated():
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = tick.__qualname__ = "test_tick"
    tick_name = f"{tick.__module__}.{tick.__name__}"

    # Simulate 5 legacy dupes for THIS tick + 1 unrelated job.
    sched.get_jobs.return_value = [
        _make_job(tick_name) for _ in range(5)
    ] + [_make_job("app.workers.reconcile_worker.run_reconcile_tick")]

    register_unique_tick(sched, tick, interval=1800)

    # Only the 5 matching dupes were cancelled; the unrelated job was untouched.
    assert sched.cancel.call_count == 5
    cancelled = [c.args[0].func_name for c in sched.cancel.call_args_list]
    assert all(n == tick_name for n in cancelled)
    # schedule called once with stable id
    sched.schedule.assert_called_once()
    kw = sched.schedule.call_args.kwargs
    assert kw["id"] == f"vfic-tick-{tick.__name__}"
    assert kw["interval"] == 1800
    assert kw["repeat"] is None


def test_no_prior_jobs_registers_cleanly():
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_clean"
    sched.get_jobs.return_value = []

    register_unique_tick(sched, tick, interval=600)

    sched.cancel.assert_not_called()
    sched.schedule.assert_called_once()
    assert sched.schedule.call_args.kwargs["id"].startswith("vfic-tick-")


def test_idempotent_after_first_registration():
    """A second call that finds the stable-id job still leaves exactly one."""
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_idemp"
    tick_name = f"{tick.__module__}.{tick.__name__}"
    stable_id = f"vfic-tick-{tick.__name__}"

    # On second boot: get_jobs returns the stable-id job (already registered).
    existing = _make_job(tick_name)
    sched.get_jobs.return_value = [existing]

    register_unique_tick(sched, tick, interval=1800)

    # It cancelled the existing one and re-registered with the same id.
    assert sched.cancel.call_count == 1
    sched.cancel.assert_called_with(existing)
    sched.schedule.assert_called_once()
    assert sched.schedule.call_args.kwargs["id"] == stable_id


def test_get_jobs_failure_is_non_fatal():
    """If get_jobs() throws, schedule() still fires (no idempotent cleanup but still registers)."""
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_fail"
    sched.get_jobs.side_effect = RuntimeError("Redis down")

    # Should NOT raise.
    register_unique_tick(sched, tick, interval=1800)

    sched.schedule.assert_called_once()
    assert sched.schedule.call_args.kwargs["id"].startswith("vfic-tick-")
