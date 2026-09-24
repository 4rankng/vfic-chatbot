"""Worker async runner regression tests."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


def test_run_async_reuses_process_local_event_loop():
    from app.workers import async_runner

    seen: list[int] = []

    async def capture() -> str:
        import asyncio

        seen.append(id(asyncio.get_running_loop()))
        return "ok"

    assert async_runner.run_async(capture()) == "ok"
    assert async_runner.run_async(capture()) == "ok"
    assert len(set(seen)) == 1

    async_runner._shutdown_loop()


def test_shutdown_closes_loop_owned_database_and_http_resources_in_order():
    from app.workers import async_runner

    async_runner._shutdown_loop()
    running_loop_ids: list[int] = []
    cleanup_order: list[str] = []

    async def capture_loop() -> None:
        running_loop_ids.append(id(asyncio.get_running_loop()))

    async def dispose_worker_engines() -> None:
        cleanup_order.append("database")
        running_loop_ids.append(id(asyncio.get_running_loop()))

    async def close_http_clients() -> None:
        cleanup_order.append("http")
        running_loop_ids.append(id(asyncio.get_running_loop()))

    with (
        patch("app.workers._db.dispose_worker_engines", dispose_worker_engines),
        patch("app.core.http.aclose_all", close_http_clients),
    ):
        async_runner.run_async(capture_loop())
        async_runner._shutdown_loop()

    assert cleanup_order == ["database", "http"]
    assert len(set(running_loop_ids)) == 1
    assert async_runner._loop is None


def test_shutdown_attempts_http_cleanup_when_database_cleanup_fails():
    from app.workers import async_runner

    async_runner._shutdown_loop()
    cleanup_order: list[str] = []

    async def fail_database_cleanup() -> None:
        cleanup_order.append("database")
        raise RuntimeError("database cleanup failed")

    async def close_http_clients() -> None:
        cleanup_order.append("http")

    with (
        patch("app.workers._db.dispose_worker_engines", fail_database_cleanup),
        patch("app.core.http.aclose_all", close_http_clients),
    ):
        async_runner.run_async(asyncio.sleep(0))
        async_runner._shutdown_loop()

    assert cleanup_order == ["database", "http"]
    assert async_runner._loop is None


def test_shutdown_attempts_http_cleanup_then_propagates_database_cancellation():
    from app.workers import async_runner

    async_runner._shutdown_loop()
    cleanup_order: list[str] = []

    async def cancel_database_cleanup() -> None:
        cleanup_order.append("database")
        raise asyncio.CancelledError

    async def close_http_clients() -> None:
        cleanup_order.append("http")

    with (
        patch("app.workers._db.dispose_worker_engines", cancel_database_cleanup),
        patch("app.core.http.aclose_all", close_http_clients),
        pytest.raises(asyncio.CancelledError),
    ):
        async_runner.run_async(asyncio.sleep(0))
        async_runner._shutdown_loop()

    assert cleanup_order == ["database", "http"]
    assert async_runner._loop is None


def test_shutdown_cancels_and_drains_pending_tasks_before_closing_resources():
    from app.workers import async_runner

    async_runner._shutdown_loop()
    task_started = asyncio.Event()
    task_finalized = asyncio.Event()
    cleanup_observations: list[bool] = []

    async def pending_publish() -> None:
        task_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            task_finalized.set()

    async def start_publish() -> None:
        asyncio.create_task(pending_publish())
        await task_started.wait()

    async def observe_finalizer() -> None:
        cleanup_observations.append(task_finalized.is_set())

    with (
        patch("app.graph.factories.aclose_client_cache", observe_finalizer),
        patch("app.workers._db.dispose_worker_engines", observe_finalizer),
        patch("app.core.http.aclose_all", observe_finalizer),
    ):
        async_runner.run_async(start_publish())
        async_runner._shutdown_loop()

    assert task_finalized.is_set()
    assert cleanup_observations == [True, True, True]
    assert async_runner._loop is None


def test_shutdown_repeats_drain_for_task_spawned_by_cancellation_finalizer():
    from app.workers import async_runner

    async_runner._shutdown_loop()
    child_started = asyncio.Event()
    child_finalized = asyncio.Event()

    async def child() -> None:
        child_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            child_finalized.set()

    parent_started = asyncio.Event()

    async def parent() -> None:
        parent_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            asyncio.create_task(child())

    async def start_parent() -> None:
        asyncio.create_task(parent())
        await parent_started.wait()

    async_runner.run_async(start_parent())
    async_runner._shutdown_loop()

    assert child_started.is_set()
    assert child_finalized.is_set()
    assert async_runner._loop is None


def test_control_flow_cancellation_propagates_from_worker_coroutine():
    from app.workers import async_runner

    async def cancelled() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        async_runner.run_async(cancelled())
    async_runner._shutdown_loop()
