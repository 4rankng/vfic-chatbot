"""Direct interactive-turn launcher tests."""
from __future__ import annotations

import asyncio

import pytest

from app.workers.chatbot_worker import run_chat_turn_job, start_direct_chat_turn


@pytest.mark.asyncio
async def test_direct_launcher_runs_the_shared_turn_executor(monkeypatch) -> None:
    observed: list[tuple[dict, str]] = []

    async def fake_run(job: dict, *, source: str) -> None:
        observed.append((job, source))

    monkeypatch.setattr("app.workers.chatbot_worker._run_job_async", fake_run)
    job = {"conversation_id": "turn-1"}

    assert start_direct_chat_turn(job) is True
    await asyncio.sleep(0)

    assert observed == [(job, "direct")]


def test_rq_entrypoint_preserves_queued_execution_source(monkeypatch) -> None:
    observed: list[tuple[dict, str]] = []

    async def fake_run(job: dict, *, source: str) -> None:
        observed.append((job, source))

    def run_now(coro) -> None:
        asyncio.run(coro)

    monkeypatch.setattr("app.workers.chatbot_worker._run_job_async", fake_run)
    monkeypatch.setattr("app.workers.async_runner.run_async", run_now)
    job = {"conversation_id": "turn-2", "execution_source": "queued"}

    run_chat_turn_job(job)

    assert observed == [(job, "queued")]
