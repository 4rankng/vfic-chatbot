"""Regression tests for the pre-flip deployment smoke wiring."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import smoke_turn
from scripts.smoke_turn import _StubAgent, _StubZalo, _build_smoke_deps, _stub_embedder


class _FakeSession:
    async def commit(self) -> None:
        return None

    async def execute(self, _statement) -> object:
        return object()


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def _patch_smoke_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcome: dict | None = None,
    turn_error: Exception | None = None,
    invariant_error: Exception | None = None,
    cleanup_error: Exception | None = None,
) -> _FakeEngine:
    engine = _FakeEngine()
    seed_session = _FakeSession()
    run_session = _FakeSession()
    cleanup_session = _FakeSession()
    sessions = [seed_session, run_session, cleanup_session]

    def _session_factory():
        if not sessions:
            raise AssertionError("unexpected session_factory() call")
        return _FakeSessionContext(sessions.pop(0))

    monkeypatch.setattr(
        smoke_turn,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://smoke"),
    )
    monkeypatch.setattr(smoke_turn, "create_async_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(smoke_turn, "async_sessionmaker", lambda *_args, **_kwargs: _session_factory)
    monkeypatch.setattr(smoke_turn.asyncio, "sleep", AsyncMock(return_value=None))

    conv = SimpleNamespace(id=uuid.uuid4(), version=7)
    identity = SimpleNamespace(id=uuid.uuid4())
    contact = SimpleNamespace(id=uuid.uuid4())
    owner = uuid.uuid4()
    monkeypatch.setattr(
        smoke_turn,
        "_seed_smoke_conversation",
        AsyncMock(return_value=(conv, identity, contact, owner)),
    )
    monkeypatch.setattr(smoke_turn, "_build_smoke_deps", lambda db: SimpleNamespace(db=db))

    async def _fake_run_turn(state, _deps):
        state.pending_message_id = 99
        if turn_error is not None:
            raise turn_error
        return outcome

    monkeypatch.setattr(smoke_turn, "run_turn", AsyncMock(side_effect=_fake_run_turn))
    monkeypatch.setattr(
        smoke_turn,
        "_assert_persisted_delivery_invariant",
        AsyncMock(side_effect=invariant_error) if invariant_error else AsyncMock(return_value=None),
        raising=False,
    )
    monkeypatch.setattr(
        smoke_turn,
        "_cleanup",
        AsyncMock(side_effect=cleanup_error) if cleanup_error else AsyncMock(return_value=None),
    )
    return engine


@pytest.mark.asyncio
async def test_run_smoke_succeeds_only_for_supported_sent_outcome(monkeypatch: pytest.MonkeyPatch):
    engine = _patch_smoke_runtime(monkeypatch, outcome={"outcome": "sent", "reply": "ok"})

    rc = await smoke_turn._run_smoke(inject_failure=False)

    assert rc == 0
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_run_smoke_fails_for_non_sent_outcome(monkeypatch: pytest.MonkeyPatch):
    _patch_smoke_runtime(
        monkeypatch,
        outcome={"outcome": "suppressed", "reason": "ownership_lost", "reply": "ok"},
    )

    rc = await smoke_turn._run_smoke(inject_failure=False)

    assert rc == 1


@pytest.mark.asyncio
async def test_run_smoke_fails_when_turn_raises(monkeypatch: pytest.MonkeyPatch):
    _patch_smoke_runtime(monkeypatch, turn_error=RuntimeError("boom"))

    rc = await smoke_turn._run_smoke(inject_failure=False)

    assert rc == 1


@pytest.mark.asyncio
async def test_run_smoke_fails_when_delivery_invariant_is_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_smoke_runtime(
        monkeypatch,
        outcome={"outcome": "sent", "reply": "ok"},
        invariant_error=AssertionError("delivery invariant missing"),
    )

    rc = await smoke_turn._run_smoke(inject_failure=False)

    assert rc == 1


@pytest.mark.asyncio
async def test_run_smoke_fails_when_cleanup_fails(monkeypatch: pytest.MonkeyPatch):
    _patch_smoke_runtime(
        monkeypatch,
        outcome={"outcome": "sent", "reply": "ok"},
        cleanup_error=RuntimeError("cleanup boom"),
    )

    rc = await smoke_turn._run_smoke(inject_failure=False)

    assert rc == 1


@pytest.mark.asyncio
async def test_run_smoke_validates_the_exact_pending_message_id(monkeypatch: pytest.MonkeyPatch):
    invariant = AsyncMock(return_value=None)
    _patch_smoke_runtime(monkeypatch, outcome={"outcome": "sent", "reply": "ok"})
    monkeypatch.setattr(smoke_turn, "_assert_persisted_delivery_invariant", invariant, raising=False)

    rc = await smoke_turn._run_smoke(inject_failure=False)

    assert rc == 0
    invariant.assert_awaited_once()
    assert invariant.await_args.kwargs["message_id"] == 99


def test_smoke_deps_skip_provider_client_construction(monkeypatch):
    from app.graph import factories
    from app.recruitment.infrastructure.service_adapters import ServiceLeadContextAdapter
    from app.services.conversation import ConversationService
    from app.services.retrieval import RetrievalRepository

    def _provider_clients_must_not_be_built(*_args, **_kwargs):
        raise AssertionError("deployment smoke must not construct provider clients")

    monkeypatch.setattr(factories, "_build_cached_clients", _provider_clients_must_not_be_built)
    db = object()

    deps = _build_smoke_deps(db)

    assert deps.db is db
    assert isinstance(deps.agent, _StubAgent)
    assert isinstance(deps.zalo, _StubZalo)
    assert deps.embedder is _stub_embedder
    assert isinstance(deps.conversation, ConversationService)
    assert isinstance(deps.retrieval, RetrievalRepository)
    assert isinstance(deps.lead, ServiceLeadContextAdapter)
