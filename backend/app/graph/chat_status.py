"""Provider-neutral lifecycle for transient native chat status.

Only the injected operation performs provider I/O. Absolute deadlines keep
request latency out of the pulse cadence; one request runs at a time and each
gets a smaller budget than the interval. Cancelling the task drains its active
request before any answer or terminal outcome may continue.
"""

from __future__ import annotations

import asyncio
from asyncio import sleep
from collections.abc import Awaitable, Callable
import logging
import math
from time import monotonic

logger = logging.getLogger(__name__)

CHAT_STATUS_MAX_INTERVAL_SECONDS = 3.0
CHAT_STATUS_REQUEST_TIMEOUT_SECONDS = 1.0


def chat_status_interval(configured_seconds: float) -> float:
    """Keep older configurations boot-compatible while capping native pulses."""
    if not math.isfinite(configured_seconds) or configured_seconds <= 0:
        return CHAT_STATUS_MAX_INTERVAL_SECONDS
    return min(configured_seconds, CHAT_STATUS_MAX_INTERVAL_SECONDS)


async def native_status_heartbeat(
    emit_status: Callable[[], Awaitable[object]], *, interval_seconds: float
) -> None:
    """Emit immediately and on regular deadlines until the owner cancels us."""
    interval = chat_status_interval(interval_seconds)
    request_timeout = min(CHAT_STATUS_REQUEST_TIMEOUT_SECONDS, interval / 2)
    clock = monotonic
    next_pulse = clock()
    while True:
        await sleep(max(0.0, next_pulse - clock()))
        try:
            async with asyncio.timeout(request_timeout):
                await emit_status()
        except Exception as exc:  # noqa: BLE001 — status must never break a turn
            logger.debug("native chat status failed error_type=%s", type(exc).__name__)
        next_pulse += interval
        # An overloaded event loop may miss a deadline. Skip expired slots
        # instead of bursting old status requests or shifting the cadence.
        now = clock()
        if next_pulse <= now:
            next_pulse += (math.floor((now - next_pulse) / interval) + 1) * interval
