"""Web composition-root shutdown lifecycle tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_exceptional_lifespan_exit_still_closes_every_resource(monkeypatch) -> None:
    from app import main

    cleanup_order: list[str] = []

    async def cleanup(name: str) -> None:
        cleanup_order.append(name)

    monkeypatch.setattr("rq_scheduler.Scheduler", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(
        "app.workers.chatbot_worker.drain_direct_chat_turns",
        lambda: cleanup("turns"),
    )
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=lambda: cleanup("database")))
    monkeypatch.setattr("app.graph.factories.aclose_client_cache", lambda: cleanup("llm"))
    monkeypatch.setattr("app.core.http.aclose_all", lambda: cleanup("http"))

    with pytest.raises(RuntimeError, match="lifespan body failed"):
        async with main.lifespan(main.app):
            raise RuntimeError("lifespan body failed")

    assert cleanup_order == ["turns", "database", "llm", "http"]


@pytest.mark.asyncio
async def test_web_cleanup_continues_then_propagates_cancellation(monkeypatch) -> None:
    from app import main

    cleanup_order: list[str] = []

    async def cancel_turns() -> None:
        cleanup_order.append("turns")
        raise asyncio.CancelledError

    async def cleanup(name: str) -> None:
        cleanup_order.append(name)

    monkeypatch.setattr("app.workers.chatbot_worker.drain_direct_chat_turns", cancel_turns)
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=lambda: cleanup("database")))
    monkeypatch.setattr("app.graph.factories.aclose_client_cache", lambda: cleanup("llm"))
    monkeypatch.setattr("app.core.http.aclose_all", lambda: cleanup("http"))

    with pytest.raises(asyncio.CancelledError):
        await main._shutdown_web_resources()

    assert cleanup_order == ["turns", "database", "llm", "http"]


@pytest.mark.asyncio
async def test_shutdown_cancellation_waits_for_real_direct_turn_before_resources(monkeypatch) -> None:
    from app import main
    from app.workers import chatbot_worker

    started = asyncio.Event()
    finalized = asyncio.Event()
    resource_observations: list[tuple[str, bool]] = []

    async def blocked_turn(job: dict, *, source: str) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()

    async def observe(name: str) -> None:
        resource_observations.append((name, finalized.is_set()))

    monkeypatch.setattr(chatbot_worker, "_run_job_async", blocked_turn)
    monkeypatch.setattr(chatbot_worker, "_DIRECT_TURN_SHUTDOWN_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=lambda: observe("database")))
    monkeypatch.setattr("app.graph.factories.aclose_client_cache", lambda: observe("llm"))
    monkeypatch.setattr("app.core.http.aclose_all", lambda: observe("http"))

    assert chatbot_worker.start_direct_chat_turn({"conversation_id": "turn-shutdown"})
    await started.wait()
    shutdown = asyncio.create_task(main._shutdown_web_resources())
    # One slice so the task exists; the cancellation is delivered at its first
    # await point — a fixed asyncio semantic, not a wall-clock race.
    await asyncio.sleep(0)
    shutdown.cancel()

    with pytest.raises(asyncio.CancelledError):
        await shutdown

    assert finalized.is_set()
    assert resource_observations == [
        ("database", True),
        ("llm", True),
        ("http", True),
    ]
