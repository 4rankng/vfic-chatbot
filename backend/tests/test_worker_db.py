"""Worker database lifetime and session-isolation contracts."""

from __future__ import annotations

from types import SimpleNamespace


def test_worker_database_state_is_loop_owned_and_sessions_are_job_scoped(monkeypatch):
    from app.workers import _db, async_runner

    async_runner._shutdown_loop()
    _db._states.clear()
    engines: list[FakeEngine] = []

    class FakeEngine:
        def __init__(self) -> None:
            self.disposed = False

        async def dispose(self) -> None:
            self.disposed = True

    class SessionContext:
        def __init__(self) -> None:
            self.session = SimpleNamespace(rollback=lambda: None)

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

    class FakeFactory:
        def __call__(self) -> SessionContext:
            return SessionContext()

    def create_engine(*args, **kwargs) -> FakeEngine:
        engine = FakeEngine()
        engines.append(engine)
        return engine

    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", create_engine)
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.async_sessionmaker",
        lambda *args, **kwargs: FakeFactory(),
    )
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+asyncpg://loopback/test",
            db_pool_size=1,
            db_max_overflow=0,
            db_pool_timeout=1,
            db_pool_recycle=60,
        ),
    )

    async def capture_lifetimes() -> tuple[int, int, int, int]:
        factory = _db.worker_session_factory()
        same_factory = _db.worker_session_factory()
        async with _db.worker_session() as first:
            first_id = id(first)
        async with _db.worker_session() as second:
            second_id = id(second)
        return id(factory), id(same_factory), first_id, second_id

    factory_id, same_factory_id, first_session_id, second_session_id = (
        async_runner.run_async(capture_lifetimes())
    )
    assert factory_id == same_factory_id
    assert first_session_id != second_session_id
    assert len(engines) == 1

    async_runner._shutdown_loop()
    assert engines[0].disposed
    assert not _db._states

    async_runner.run_async(capture_lifetimes())
    assert len(engines) == 2
    async_runner._shutdown_loop()
