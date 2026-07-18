from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.workers import decision_trace_retention_worker


class _ScalarRows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _FakeDb:
    def __init__(self, ids):
        self.ids = ids
        self.executed = []
        self.commits = 0

    async def scalars(self, _statement):
        return _ScalarRows(self.ids)

    async def execute(self, statement):
        self.executed.append(statement)

    async def commit(self):
        self.commits += 1


def _install_worker_dependencies(monkeypatch, db: _FakeDb) -> None:
    from app.core import config
    from app.workers import _db

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            decision_trace_retention_days=30,
            decision_trace_retention_batch_size=200,
        ),
    )

    @asynccontextmanager
    async def _worker_session():
        yield db

    monkeypatch.setattr(_db, "worker_session", _worker_session)


@pytest.mark.asyncio
async def test_retention_tick_nulls_only_selected_trace_rows(monkeypatch) -> None:
    db = _FakeDb([11, 12])
    _install_worker_dependencies(monkeypatch, db)

    await decision_trace_retention_worker._run_tick_async()

    assert db.commits == 1
    assert len(db.executed) == 1
    sql = str(db.executed[0].compile(compile_kwargs={"literal_binds": True}))
    assert "decision_trace=NULL" in sql.replace(" ", "")
    assert "bot_runs.id IN (11, 12)" in sql
    assert "proposed_reply" not in sql


@pytest.mark.asyncio
async def test_retention_tick_is_a_noop_when_nothing_expired(monkeypatch) -> None:
    db = _FakeDb([])
    _install_worker_dependencies(monkeypatch, db)

    await decision_trace_retention_worker._run_tick_async()

    assert db.executed == []
    assert db.commits == 0

