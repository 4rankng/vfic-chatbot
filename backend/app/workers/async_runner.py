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
    async def shutdown_resources() -> None:
        from app.core.http import aclose_all
        from app.graph.factories import aclose_client_cache
        from app.workers._db import dispose_worker_engines

        cancellation: asyncio.CancelledError | None = None
        for resource_name, cleanup in (
            ("LLM clients", aclose_client_cache),
            ("database engines", dispose_worker_engines),
            ("HTTP clients", aclose_all),
        ):
            try:
                await cleanup()
            except asyncio.CancelledError as exc:
                # Each resource owns independent process-lifetime state. Finish
                # closing the others before preserving cancellation semantics.
                cancellation = cancellation or exc
                logger.warning(
                    "worker shutdown cleanup cancelled resource=%s",
                    resource_name,
                    exc_info=True,
                )
            except Exception:  # noqa: BLE001 - one cleanup must not block the next
                logger.warning(
                    "worker shutdown cleanup failed resource=%s",
                    resource_name,
                    exc_info=True,
                )
        if cancellation is not None:
            raise cancellation

    cancellation: asyncio.CancelledError | None = None
    try:
        async def drain_pending_tasks() -> None:
            current = asyncio.current_task()
            deadline = loop.time() + 5.0
            while True:
                pending = [
                    task
                    for task in asyncio.all_tasks(loop)
                    if task is not current and not task.done()
                ]
                if not pending:
                    return
                for task in pending:
                    task.cancel()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    logger.warning(
                        "worker shutdown timed out draining tasks count=%d",
                        len(pending),
                    )
                    return
                _done, still_pending = await asyncio.wait(pending, timeout=remaining)
                if still_pending:
                    logger.warning(
                        "worker shutdown timed out draining tasks count=%d",
                        len(still_pending),
                    )
                    return

        loop.run_until_complete(drain_pending_tasks())
        loop.run_until_complete(loop.shutdown_asyncgens())
        try:
            loop.run_until_complete(shutdown_resources())
        except asyncio.CancelledError as exc:
            cancellation = exc
        except Exception:  # noqa: BLE001
            logger.warning("worker async runner shutdown failed", exc_info=True)
        loop.run_until_complete(loop.shutdown_default_executor())
    finally:
        loop.close()
        _loop = None
    if cancellation is not None:
        raise cancellation


atexit.register(_shutdown_loop)
