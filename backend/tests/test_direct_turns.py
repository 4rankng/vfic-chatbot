"""Direct interactive-turn launcher tests."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import db as core_db
from app.services.conversation.state import ConversationState
from app.workers import chatbot_worker, direct_turn
from app.workers.chatbot_worker import run_chat_turn_job
from app.workers.direct_turn import (
    drain_direct_chat_turns,
    start_direct_chat_turn,
)


def _session_factory():
    """A DB session the heartbeat can open, close, and renew against."""
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db



@pytest.mark.asyncio
async def test_direct_launcher_runs_the_shared_turn_executor(monkeypatch) -> None:
    observed: list[tuple[dict, str]] = []

    async def fake_run(job: dict, *, source: str) -> None:
        observed.append((job, source))

    monkeypatch.setattr("app.workers.chatbot_worker._run_job_async", fake_run)
    job = {"conversation_id": "turn-1"}

    assert start_direct_chat_turn(job) is True
    (task,) = direct_turn._direct_turn_tasks
    await task  # await the real handle instead of pumping the loop

    assert observed == [(job, "direct")]
    assert direct_turn._direct_turn_tasks == set()


@pytest.mark.asyncio
async def test_direct_turn_drain_cancels_straggler_before_resource_shutdown(monkeypatch) -> None:
    started = asyncio.Event()
    finalized = asyncio.Event()

    async def blocked_run(job: dict, *, source: str) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()

    monkeypatch.setattr("app.workers.chatbot_worker._run_job_async", blocked_run)

    assert start_direct_chat_turn({"conversation_id": "turn-pending"}) is True
    await started.wait()
    assert len(direct_turn._direct_turn_tasks) == 1

    await drain_direct_chat_turns(timeout_seconds=0)

    assert finalized.is_set()
    assert direct_turn._direct_turn_tasks == set()


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


@pytest.mark.asyncio
async def test_trace_context_setup_failure_does_not_mask_original_error(monkeypatch) -> None:
    trace_context = MagicMock()
    trace_context.set.side_effect = RuntimeError("trace setup failed")
    monkeypatch.setattr(chatbot_worker, "trace_id_ctx", trace_context)

    with pytest.raises(RuntimeError, match="trace setup failed"):
        await chatbot_worker._run_job_async_inner(
            {
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "version_at_start": 1,
                "user_text": "xin chào",
            },
            source="direct",
        )

    trace_context.reset.assert_not_called()


def test_the_direct_bridge_is_reachable_from_both_module_paths() -> None:
    """The bridge moved to ``direct_turn``; the old import sites still resolve.

    ``app.main``'s shutdown hook imports ``drain_direct_chat_turns`` from
    ``chatbot_worker``. A split that dropped the re-export would leave that
    import failing only at shutdown time — after every inbound message is
    already being served — so the re-export is pinned here.
    """
    assert chatbot_worker.start_direct_chat_turn is direct_turn.start_direct_chat_turn
    assert chatbot_worker.drain_direct_chat_turns is direct_turn.drain_direct_chat_turns
    assert "start_direct_chat_turn" in chatbot_worker.__all__
    assert "drain_direct_chat_turns" in chatbot_worker.__all__


@pytest.mark.asyncio
async def test_direct_lease_heartbeat_renews_through_state_until_the_lease_is_gone(
    monkeypatch,
) -> None:
    """The heartbeat renews on its own session and stops when the lease is lost.

    A direct turn's DB session belongs to the turn, so without this heartbeat the
    durable lease expires mid-generation and the reconcile sweep force-breaks a
    live turn's lock. It must therefore keep calling the real
    ``ConversationState.renew_lock`` and stop the moment that call reports the
    lease is no longer owned (a recruiter takeover, or an expired TTL) — polling
    on afterwards would fight whoever holds the conversation.
    """
    renewals: list[tuple[uuid.UUID, str]] = []

    async def _renew(self, conv_id, *, lock_owner, ttl_seconds=None):
        renewals.append((conv_id, lock_owner))
        return len(renewals) < 3  # owned twice, then taken over

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(direct_turn_heartbeat_seconds=0),
    )
    # ``app.core.db`` exposes ``async_session`` through a lazy module
    # ``__getattr__``, so the attribute has to be installed onto the module
    # rather than patched by name.
    monkeypatch.setattr(core_db, "async_session", _session_factory, raising=False)
    monkeypatch.setattr(ConversationState, "renew_lock", _renew)

    conv_id = uuid.uuid4()
    lock_owner = str(uuid.uuid4())
    await asyncio.wait_for(
        direct_turn.renew_direct_lock(
            {"conversation_id": str(conv_id), "lock_owner": lock_owner}
        ),
        timeout=5,
    )

    assert renewals == [(conv_id, lock_owner)] * 3


@pytest.mark.asyncio
async def test_direct_lease_heartbeat_never_polls_without_an_owner_token(monkeypatch) -> None:
    """A job carrying no owner token must not renew at all.

    ``renew_lock`` with no ``lock_owner`` is a *take*, not a renew: a heartbeat
    that looped on it would hand itself the per-chat mutex it is supposed to be
    protecting, and two turns would answer the same conversation.
    """
    renewed = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(direct_turn_heartbeat_seconds=0),
    )
    # ``app.core.db`` exposes ``async_session`` through a lazy module
    # ``__getattr__``, so the attribute has to be installed onto the module
    # rather than patched by name.
    monkeypatch.setattr(core_db, "async_session", _session_factory, raising=False)
    monkeypatch.setattr(ConversationState, "renew_lock", renewed)

    await asyncio.wait_for(
        direct_turn.renew_direct_lock({"conversation_id": str(uuid.uuid4())}),
        timeout=1,
    )

    renewed.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_lease_heartbeat_rejects_a_malformed_conversation_id(
    monkeypatch,
) -> None:
    """A job whose conversation id is not a UUID must not reach the lock SQL.

    The id comes off the queue payload, so a malformed one has to be dropped at
    the boundary rather than passed to the update.
    """
    renewed = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(direct_turn_heartbeat_seconds=0),
    )
    # ``app.core.db`` exposes ``async_session`` through a lazy module
    # ``__getattr__``, so the attribute has to be installed onto the module
    # rather than patched by name.
    monkeypatch.setattr(core_db, "async_session", _session_factory, raising=False)
    monkeypatch.setattr(ConversationState, "renew_lock", renewed)

    await asyncio.wait_for(
        direct_turn.renew_direct_lock(
            {"conversation_id": "not-a-uuid", "lock_owner": str(uuid.uuid4())}
        ),
        timeout=1,
    )

    renewed.assert_not_awaited()


async def test_typing_bridge_survives_failures_and_has_no_four_pulse_limit(monkeypatch):
    from app.services.integration_settings import IntegrationSettingsService
    import app.services.webhook as webhook

    attempts = []
    sixth = asyncio.Event()
    resolve = AsyncMock(side_effect=[
        RuntimeError("temporary credential read failure"),
        *[SimpleNamespace(bot_token="current-token") for _ in range(10)],
    ])

    async def emit(chat_id, token):
        attempts.append((chat_id, token))
        if len(attempts) == 1:
            raise RuntimeError("temporary provider failure")
        if len(attempts) >= 6:
            sixth.set()

    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(
        typing_heartbeat_seconds=0.02,
    ))
    monkeypatch.setattr(core_db, "async_session", _session_factory, raising=False)
    monkeypatch.setattr(IntegrationSettingsService, "resolve_zalo", resolve)
    monkeypatch.setattr(webhook, "_fire_typing", emit)
    task = asyncio.create_task(direct_turn.bridge_typing("candidate"))
    try:
        await asyncio.wait_for(sixth.wait(), timeout=1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert attempts == [("candidate", "current-token")] * 6
    assert resolve.await_count == 7


async def test_typing_bridge_never_falls_back_to_stale_environment_token(monkeypatch):
    from app.services.integration_settings import IntegrationSettingsService
    import app.services.webhook as webhook

    resolve = AsyncMock(return_value=SimpleNamespace(bot_token=None))
    emit = AsyncMock()
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(
        typing_heartbeat_seconds=0.02, zalo_bot_token="stale-environment-token",
    ))
    monkeypatch.setattr(core_db, "async_session", _session_factory, raising=False)
    monkeypatch.setattr(IntegrationSettingsService, "resolve_zalo", resolve)
    monkeypatch.setattr(webhook, "_fire_typing", emit)
    task = asyncio.create_task(direct_turn.bridge_typing("candidate"))
    try:
        await asyncio.sleep(0.065)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert resolve.await_count >= 3
    emit.assert_not_awaited()


@pytest.mark.parametrize("setup_failure", [False, True])
async def test_worker_transfers_live_setup_status_to_runner_and_drains_errors(
    monkeypatch, setup_failure,
):
    from contextlib import asynccontextmanager
    import app.graph.factories as factories
    import app.graph.runner as runner
    import app.workers._db as worker_db

    started = asyncio.Event()
    drained = asyncio.Event()
    events = []

    async def bridge(*args):
        events.append("status-started")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.01)
            events.append("status-drained")
            drained.set()

    @asynccontextmanager
    async def session():
        yield object()

    async def build(*args, **kwargs):
        await started.wait()
        events.append("setup-completed")
        if setup_failure:
            raise RuntimeError("dependency setup failed")
        return SimpleNamespace(persist=None)

    async def run(state, deps):
        assert not drained.is_set()
        assert deps.preamble_status_task is not None
        deps.preamble_status_task.cancel()
        await asyncio.gather(deps.preamble_status_task, return_exceptions=True)
        assert drained.is_set()
        events.append("real-answer")

    monkeypatch.setattr(chatbot_worker, "_bridge_typing", bridge)
    monkeypatch.setattr(worker_db, "worker_session", session)
    monkeypatch.setattr(worker_db, "worker_session_factory", lambda: None)
    monkeypatch.setattr(factories, "build_deps", build)
    monkeypatch.setattr(runner, "run_turn", run)
    monkeypatch.setattr(chatbot_worker, "_handoff_to_newer_inbound", AsyncMock())
    job = {
        "conversation_id": str(uuid.uuid4()), "version_at_start": 1,
        "user_text": "Tôi muốn ứng tuyển", "zalo_channel": "bot", "zalo_chat_id": "candidate",
    }
    if setup_failure:
        with pytest.raises(RuntimeError, match="dependency setup failed"):
            await chatbot_worker._run_job_async_inner(job, source="direct")
        assert events == ["status-started", "setup-completed", "status-drained"]
    else:
        await chatbot_worker._run_job_async_inner(job, source="direct")
        assert events == ["status-started", "setup-completed", "status-drained", "real-answer"]
    assert drained.is_set()


async def test_queued_status_starts_before_slow_queue_telemetry(monkeypatch):
    from contextlib import asynccontextmanager
    import app.graph.factories as factories
    import app.graph.runner as runner
    import app.workers._db as worker_db

    started = asyncio.Event()
    drained = asyncio.Event()
    events = []

    async def bridge(*args):
        events.append("status-started")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()

    async def slow_metric(*args):
        await started.wait()
        assert not drained.is_set()
        events.append("queue-depth")
        return 5

    @asynccontextmanager
    async def session():
        yield object()

    async def run(state, deps):
        assert state.queue_depth == 5
        assert not drained.is_set()
        assert deps.preamble_status_task is not None
        deps.preamble_status_task.cancel()
        await asyncio.gather(deps.preamble_status_task, return_exceptions=True)
        events.append("real-answer")

    monkeypatch.setattr(chatbot_worker, "_bridge_typing", bridge)
    monkeypatch.setattr(asyncio, "to_thread", slow_metric)
    monkeypatch.setattr(worker_db, "worker_session", session)
    monkeypatch.setattr(worker_db, "worker_session_factory", lambda: None)
    monkeypatch.setattr(factories, "build_deps", AsyncMock(return_value=SimpleNamespace(persist=None)))
    monkeypatch.setattr(runner, "run_turn", run)
    monkeypatch.setattr(chatbot_worker, "_handoff_to_newer_inbound", AsyncMock())
    await chatbot_worker._run_job_async_inner({
        "conversation_id": str(uuid.uuid4()), "version_at_start": 1,
        "user_text": "Tôi muốn ứng tuyển", "zalo_channel": "bot", "zalo_chat_id": "candidate",
    }, source="queued")
    assert events == ["status-started", "queue-depth", "real-answer"]
    assert drained.is_set()


async def test_typing_bridge_bounds_slow_credential_reads_and_retries(monkeypatch):
    from app.services.integration_settings import IntegrationSettingsService
    import app.services.webhook as webhook

    third_attempt = asyncio.Event()
    attempts = 0
    active = 0
    maximum_active = 0
    cancelled = 0

    async def resolve(*args, **kwargs):
        nonlocal attempts, active, maximum_active, cancelled
        attempts += 1
        active += 1
        maximum_active = max(maximum_active, active)
        if attempts == 3:
            third_attempt.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
            cancelled += 1

    emit = AsyncMock()
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(
        typing_heartbeat_seconds=0.02,
    ))
    monkeypatch.setattr(core_db, "async_session", _session_factory, raising=False)
    monkeypatch.setattr(IntegrationSettingsService, "resolve_zalo", resolve)
    monkeypatch.setattr(webhook, "_fire_typing", emit)
    task = asyncio.create_task(direct_turn.bridge_typing("candidate"))
    try:
        await asyncio.wait_for(third_attempt.wait(), timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert attempts >= 3
    assert maximum_active == 1 and active == 0
    assert cancelled == attempts
    emit.assert_not_awaited()
