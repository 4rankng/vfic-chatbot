"""Stable RQ entrypoint for durable outbound recovery."""

from __future__ import annotations


def run_outbound_dispatch_tick() -> None:
    """RQ scheduler entrypoint; dispatches commands left PENDING after a crash."""
    from app.workers.async_runner import run_async

    run_async(_dispatch_pending())


async def _dispatch_pending() -> None:
    from app.composition.conversation_messaging import run_outbound_recovery

    await run_outbound_recovery()
