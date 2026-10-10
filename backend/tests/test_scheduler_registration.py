"""Tests for register_unique_tick / register_unique_cron_tick — mock-based, no Redis/DB required."""

import inspect
from unittest.mock import MagicMock

from rq_scheduler import Scheduler

from app.workers.scheduler_utils import register_unique_cron_tick, register_unique_tick


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
    sched.get_jobs.return_value = [_make_job(tick_name) for _ in range(5)] + [
        _make_job("app.workers.reconcile_worker.run_reconcile_tick")
    ]

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


# --- register_unique_cron_tick (wall-clock-pinned variant) --------------------


def test_cron_cancels_matching_jobs_and_keeps_unrelated():
    """Cron variant mirrors interval variant: dedupes this tick only, keeps others."""
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = tick.__qualname__ = "test_cron_tick"
    tick_name = f"{tick.__module__}.{tick.__name__}"

    sched.get_jobs.return_value = [_make_job(tick_name) for _ in range(3)] + [
        _make_job("app.workers.reconcile_worker.run_reconcile_tick")
    ]

    register_unique_cron_tick(sched, tick, cron_string="0 20 * * *")

    assert sched.cancel.call_count == 3
    cancelled = [c.args[0].func_name for c in sched.cancel.call_args_list]
    assert all(n == tick_name for n in cancelled)
    # cron() called once with stable id + the supplied expression up front
    sched.cron.assert_called_once()
    args, kw = sched.cron.call_args
    assert args[0] == "0 20 * * *"
    assert kw["id"] == f"vfic-tick-{tick.__name__}"
    assert kw["repeat"] is None
    # Must NOT have touched the interval API
    sched.schedule.assert_not_called()


def test_cron_no_prior_jobs_registers_cleanly():
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_cron_clean"
    sched.get_jobs.return_value = []

    register_unique_cron_tick(sched, tick, cron_string="0 3 * * *")

    sched.cancel.assert_not_called()
    sched.cron.assert_called_once()
    assert sched.cron.call_args.kwargs["id"].startswith("vfic-tick-")


def test_cron_registers_the_requested_job_timeout():
    """The digest tick outgrew RQ's 180s default and was killed mid-run on
    2026-10-10; the caller must be able to hand the job a longer ceiling, and
    omitting it must leave RQ's default in place."""
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_cron_timeout"
    sched.get_jobs.return_value = []

    register_unique_cron_tick(sched, tick, cron_string="8 * * * *", job_timeout_seconds=900)

    # rq-scheduler names it ``timeout``; ``job_timeout`` is not a parameter
    # of Scheduler.cron and raises TypeError at boot.
    assert sched.cron.call_args.kwargs["timeout"] == 900


def test_cron_without_a_timeout_keeps_the_default():
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_cron_default_timeout"
    sched.get_jobs.return_value = []

    register_unique_cron_tick(sched, tick, cron_string="8 * * * *")

    assert "timeout" not in sched.cron.call_args.kwargs


def test_cron_kwargs_are_accepted_by_the_real_scheduler_signature():
    """A MagicMock accepts any keyword, so the mock tests above cannot catch a
    keyword rq-scheduler does not have. Shipping `job_timeout` instead of
    `timeout` raised TypeError at every web boot on 2026-10-10 and silently
    unregistered the digest tick; bind against the real signature instead."""

    def _tick() -> None:
        return None

    bound = inspect.signature(Scheduler.cron).bind(
        object(),
        "8 * * * *",
        _tick,
        repeat=None,
        id="vfic-tick-probe",
        timeout=900,
    )
    assert bound.arguments["timeout"] == 900


def test_cron_idempotent_after_first_registration():
    """A second boot that finds the stable-id job still leaves exactly one."""
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_cron_idemp"
    tick_name = f"{tick.__module__}.{tick.__name__}"
    stable_id = f"vfic-tick-{tick.__name__}"

    existing = _make_job(tick_name)
    sched.get_jobs.return_value = [existing]

    register_unique_cron_tick(sched, tick, cron_string="0 20 * * *")

    assert sched.cancel.call_count == 1
    sched.cancel.assert_called_with(existing)
    sched.cron.assert_called_once()
    assert sched.cron.call_args.kwargs["id"] == stable_id


def test_cron_get_jobs_failure_is_non_fatal():
    """If get_jobs() throws, cron() still fires (no idempotent cleanup but still registers)."""
    sched = MagicMock()
    tick = lambda: None  # noqa: E731
    tick.__module__ = "test_cron_fail"
    sched.get_jobs.side_effect = RuntimeError("Redis down")

    # Should NOT raise.
    register_unique_cron_tick(sched, tick, cron_string="0 20 * * *")

    sched.cron.assert_called_once()
    assert sched.cron.call_args.kwargs["id"].startswith("vfic-tick-")
