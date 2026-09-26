"""Unit coverage for the turn-pipeline gate's decision path and wiring.

The SQL is covered by ``tests/integration/test_turn_pipeline_check.py``; this
file covers what the gate *does* with the results: which conditions fail the
deploy, how the consumer count is read from the RQ registry, and the self-test
knob that proves the failure path actually fails.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import redis as redis_lib

from scripts import turn_pipeline_check as gate


class _FakeRedis:
    def __init__(self, depths: dict[str, int], *, raise_on: str | None = None) -> None:
        self._depths = depths
        self._raise_on = raise_on

    def llen(self, key: str) -> int:
        queue = key.removeprefix("rq:queue:")
        if queue == self._raise_on:
            raise redis_lib.RedisError("boom")
        return self._depths.get(queue, 0)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        redis_url="redis://localhost:6379/0",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
    )


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    consumers: dict[str, int],
    stalled: list[tuple[str, str]] | None = None,
    stale: list[tuple[int, str]] | None = None,
) -> None:
    monkeypatch.setattr(gate, "get_settings", lambda: _settings())
    monkeypatch.setattr(gate, "_redis_connection", lambda _settings: _FakeRedis({}))
    monkeypatch.setattr(gate, "_live_worker_queues", lambda _client: consumers)
    monkeypatch.setattr(
        gate, "_stalled_conversations", AsyncMock(return_value=list(stalled or []))
    )
    monkeypatch.setattr(gate, "_stale_pending", AsyncMock(return_value=list(stale or [])))
    monkeypatch.setattr(gate, "create_async_engine", lambda *_a, **_k: _FakeEngine())


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeEngine:
    async def dispose(self) -> None:
        return None


def _patch_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate, "async_sessionmaker", lambda *_a, **_k: (lambda: _FakeSession())
    )


@pytest.mark.asyncio
async def test_passes_when_consumers_live_and_nothing_stalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(monkeypatch, consumers={"webhook_high": 3, "recovery": 3})
    _patch_session_factory(monkeypatch)

    assert (
        await gate._run_check(
            window_seconds=300, stale_after_seconds=120, min_consumers=1
        )
        == 0
    )


@pytest.mark.asyncio
async def test_fails_when_no_consumer_is_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The exact 2026-09-26 shape: webhooks accepted, nothing consuming them.
    _patch_runtime(monkeypatch, consumers={"maintenance": 1})
    _patch_session_factory(monkeypatch)

    assert (
        await gate._run_check(
            window_seconds=300, stale_after_seconds=120, min_consumers=1
        )
        == 1
    )


@pytest.mark.asyncio
async def test_fails_when_a_conversation_awaits_a_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(
        monkeypatch,
        consumers={"webhook_high": 3},
        stalled=[("conv-1", "2026-09-26T05:15:56+00:00")],
    )
    _patch_session_factory(monkeypatch)

    assert (
        await gate._run_check(
            window_seconds=300, stale_after_seconds=120, min_consumers=1
        )
        == 1
    )


@pytest.mark.asyncio
async def test_fails_when_outbound_rows_are_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(
        monkeypatch,
        consumers={"webhook_high": 3},
        stale=[(42, "2026-09-26T05:00:00+00:00")],
    )
    _patch_session_factory(monkeypatch)

    assert (
        await gate._run_check(
            window_seconds=300, stale_after_seconds=120, min_consumers=1
        )
        == 1
    )


@pytest.mark.asyncio
async def test_min_consumers_is_the_self_test_knob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--min-consumers 999` MUST fail: this is the documented self-test."""
    _patch_runtime(monkeypatch, consumers={"webhook_high": 3})
    _patch_session_factory(monkeypatch)

    assert (
        await gate._run_check(
            window_seconds=300, stale_after_seconds=120, min_consumers=999
        )
        == 1
    )


def test_queue_depths_reads_each_queue_and_tolerates_redis_errors() -> None:
    client = _FakeRedis({"webhook_high": 4, "recovery": 2}, raise_on="maintenance")

    depths = gate._queue_depths(client)

    assert depths == {"webhook_high": 4, "recovery": 2, "maintenance": -1}


def test_live_worker_queues_counts_registrations_per_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workers = [
        SimpleNamespace(queues=[SimpleNamespace(name="webhook_high")]),
        SimpleNamespace(queues=[SimpleNamespace(name="webhook_high")]),
        SimpleNamespace(queues=[SimpleNamespace(name="recovery")]),
        SimpleNamespace(queues=[]),
    ]

    class _FakeWorker:
        @staticmethod
        def all(connection):  # noqa: ANN001, ARG004
            return workers

    monkeypatch.setattr("rq.Worker", _FakeWorker)

    counts = gate._live_worker_queues(object())

    assert counts == {"webhook_high": 2, "recovery": 1}


def test_live_worker_queues_never_masks_a_stall_on_registry_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExplodingWorker:
        @staticmethod
        def all(connection):  # noqa: ANN001, ARG004
            raise RuntimeError("registry unavailable")

    monkeypatch.setattr("rq.Worker", _ExplodingWorker)

    # An unreadable registry yields no counts, so the consumer assertion fails
    # closed rather than reporting a healthy pipeline it cannot observe.
    assert gate._live_worker_queues(object()) == {}
