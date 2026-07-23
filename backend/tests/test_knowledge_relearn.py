from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.knowledge import service as knowledge_service
from app.services.knowledge.service import KnowledgeService


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

    async def scalars(self, _statement):
        return _Scalars(self.rows)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_reindex_all_enqueues_sources_clears_caches_and_audits(monkeypatch):
    docs = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
    db = _DB(docs)
    enqueued: list[uuid.UUID] = []
    cache_repairs = 0
    audits: list[dict] = []

    class _Jobs:
        def ingest_document(self, document_id):
            enqueued.append(document_id)

    async def _repair_caches():
        nonlocal cache_repairs
        cache_repairs += 1

    async def _audit(_db, **kwargs):
        audits.append(kwargs)

    service = KnowledgeService(db)
    monkeypatch.setattr(service, "_job_scheduler", lambda: _Jobs())
    monkeypatch.setattr(knowledge_service, "bump_kb_caches", _repair_caches)
    monkeypatch.setattr(knowledge_service, "record_audit", _audit)

    result = await service.reindex_all(SimpleNamespace(id=uuid.uuid4()))

    assert result == 2
    assert enqueued == [doc.id for doc in docs]
    assert cache_repairs == 1
    assert audits[0]["action"] == "knowledge_relearn_all_enqueued"
    assert audits[0]["payload"] == {"queued": 2}
    assert db.commits == 1
