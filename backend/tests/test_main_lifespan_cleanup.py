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
