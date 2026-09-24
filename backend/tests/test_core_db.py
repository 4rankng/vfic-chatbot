"""Lazy engine wiring in ``app.core.db``.

Importing the module (directly or via ``app.models.base`` importers) must not
bind the production pool configuration; the first attribute access builds the
one process engine, and the integration conftest's attribute swap still rebinds
``get_db``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def test_importing_core_db_does_not_build_the_engine():
    """A bare import opens no pool: engine construction is behind first access.

    Runs in a subprocess so the patched constructor can never leak into this
    process's already-imported module.
    """
    probe = textwrap.dedent(
        """
        import sys
        import sqlalchemy.ext.asyncio as aio

        def refused(*args, **kwargs):
            raise AssertionError("create_async_engine must not run at import time")

        aio.create_async_engine = refused
        import app.core.db as db

        sys.exit(0 if db._engine is None and db._session_factory is None else 1)
        """
    )
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_engine_and_session_factory_are_built_once_and_shared(monkeypatch):
    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None, raising=False)
    monkeypatch.setattr(db_module, "_session_factory", None, raising=False)

    engine_first = db_module.engine
    engine_again = db_module.engine
    factory = db_module.async_session

    assert engine_first is engine_again
    assert factory is db_module.async_session
    assert factory.kw["bind"] is engine_first


@pytest.mark.asyncio
async def test_get_db_resolves_the_session_factory_at_call_time(monkeypatch):
    """The integration conftest rebinds ``db.async_session``; get_db must follow.

    A direct module-global read would freeze the original factory and silently
    point the app at the wrong database during integration runs.
    """
    import app.core.db as db_module

    class _Session:
        def __init__(self) -> None:
            self.rolled_back = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def rollback(self):
            self.rolled_back = True

    class _Factory:
        def __init__(self) -> None:
            self.created: list[_Session] = []

        def __call__(self):
            session = _Session()
            self.created.append(session)
            return session

    factory = _Factory()
    monkeypatch.setattr(db_module, "async_session", factory, raising=False)

    generator = db_module.get_db()
    session = await generator.__anext__()
    assert session is factory.created[0]

    # Happy path: plain exhaustion closes the dependency without rollback.
    with pytest.raises(StopAsyncIteration):
        await generator.__anext__()
    assert session.rolled_back is False

    # Error path: the exception propagates after a rollback.
    generator = db_module.get_db()
    await generator.__anext__()
    with pytest.raises(RuntimeError, match="turn failed"):
        await generator.athrow(RuntimeError("turn failed"))
    assert factory.created[-1].rolled_back is True
