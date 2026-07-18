from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api import knowledge


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    async def execute(self, _statement):
        return _Result(self.rows)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_reindex_all_enqueues_sources_clears_caches_and_audits(monkeypatch):
    docs = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    db = _DB(docs)
    enqueued: list[uuid.UUID] = []
    cache_bumps: list[str] = []
    audits: list[dict] = []

    monkeypatch.setattr(knowledge, "enqueue_ingest", enqueued.append)

    async def _bump(namespace: str):
        cache_bumps.append(namespace)

    async def _audit(_db, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(knowledge, "bump_cache_version", _bump)
    monkeypatch.setattr(knowledge, "record_audit", _audit)

    result = await knowledge.reindex_all(
        admin=SimpleNamespace(id=uuid.uuid4()),
        db=db,
    )

    assert result == {"status": "ok", "queued": 2}
    assert enqueued == [doc.id for doc in docs]
    assert cache_bumps == ["knowledge", "semantic_cache"]
    assert audits[0]["action"] == "knowledge_relearn_all_enqueued"
    assert audits[0]["payload"] == {"queued": 2}
    assert db.commits == 1
