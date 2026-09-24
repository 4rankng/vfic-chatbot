"""The RQ entrypoint for durable outbound recovery is a thin delegator.

Behavior is asserted by executing the entrypoint; the only source-text checks
kept here are absence guards (the entrypoint must not grow recovery internals).
"""

from __future__ import annotations


from app.workers import async_runner, outbound_dispatch_worker


async def test_tick_schedules_the_recovery_and_its_chain_runs_it(monkeypatch) -> None:
    """Executing the entrypoint must schedule the real delegation chain; awaiting
    the scheduled coroutine runs run_outbound_recovery."""
    ran = []

    async def fake_recovery() -> None:
        ran.append("recovery")

    scheduled = []

    def fake_run_async(coro):
        scheduled.append(coro)

    monkeypatch.setattr(async_runner, "run_async", fake_run_async)
    monkeypatch.setattr(
        "app.composition.conversation_messaging.run_outbound_recovery", fake_recovery
    )

    outbound_dispatch_worker.run_outbound_dispatch_tick()
    assert len(scheduled) == 1
    await scheduled[0]
    assert ran == ["recovery"]


def test_worker_keeps_stable_entrypoint_without_recovery_internals() -> None:
    """Absence guards: the stable entrypoint must not grow recovery internals,
    so the durable recovery stays owned by the composition root."""
    import inspect

    source = inspect.getsource(outbound_dispatch_worker)

    assert "app.models" not in source
    assert "app.services" not in source
    assert "dispatch_outbox" not in source
    assert "claim_stale_sending_unknown" not in source
