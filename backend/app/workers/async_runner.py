"""Shared async runner for sync RQ job entrypoints.

RQ calls job functions synchronously.  Keeping one event loop per worker process
lets async clients and SQLAlchemy engines stay bound to a stable loop instead of
being recreated for every job.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
from collections.abc import Awaitable
from typing import TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_async(awaitable: Awaitable[T]) -> T:
    """Run *awaitable* on the process-local worker event loop."""
    loop = _get_loop()
    if loop.is_running():
        raise RuntimeError("worker async runner cannot be called from a running event loop")
    return loop.run_until_complete(awaitable)


def _shutdown_loop() -> None:
    global _loop
    loop = _loop
    if loop is None or loop.is_closed():
        return
    try:
        from app.workers._db import dispose_worker_engines

        loop.run_until_complete(dispose_worker_engines())
    except Exception:  # noqa: BLE001
        logger.warning("worker async runner shutdown failed", exc_info=True)
    finally:
        loop.close()
        _loop = None


atexit.register(_shutdown_loop)
