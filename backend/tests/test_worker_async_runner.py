"""Worker async runner regression tests."""
from __future__ import annotations


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
