"""Post-ingest feature extraction: the structured layer must follow the KB.

Operator rule: uploading a training template reaches BOTH knowledge layers —
the KB categories/chunks AND the structured JobFeatureValue rows that
``compare_income`` reads. The 4P/AMTRAN/SDS onboarding shipped with an empty
structured layer because extraction only existed as a manual admin button.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers import ingest_worker as w

_SENTINEL = object()


class _FakeSessionCM:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_exc):
        return False


def _doc(project_id):
    return SimpleNamespace(id=uuid.uuid4(), project_id=project_id, raw_text="brief")


def _install_fakes(monkeypatch, *, doc, latest, pipeline_calls, pipeline_raises=False):
    project_id = uuid.uuid4()
    real_doc = doc if doc is not None else None

    class _FakeRepo:
        def __init__(self, db):
            pass

        async def get_latest_document_with_text(self, _project_id):
            return latest

    class _FakePipeline:
        # Positional mirror of KnowledgePipeline(db, embedder, llm_json, ...).
        def __init__(self, db, embedder=None, llm_json=None, call_timeout=None):
            self.embedder = embedder
            self.llm_json = llm_json

        async def extract_product_features(self, document, evidence):
            pipeline_calls.append((document, self.embedder, self.llm_json))
            if pipeline_raises:
                raise RuntimeError("extractor exploded")

    monkeypatch.setattr(
        "app.services.project.repository.ProjectRepository", _FakeRepo
    )
    monkeypatch.setattr("app.services.knowledge.KnowledgePipeline", _FakePipeline)

    db = AsyncMock()
    db.get = AsyncMock(return_value=real_doc)
    monkeypatch.setattr("app.workers._db.worker_session", lambda: _FakeSessionCM(db))

    ingestion = AsyncMock()
    ingestion.ingest_document = AsyncMock(return_value=None)
    assert pipeline_calls is not None
    monkeypatch.setattr(
        "app.composition.project_knowledge.build_knowledge_ingestion",
        lambda db: ingestion,
    )
    return project_id, ingestion


@pytest.mark.asyncio
async def test_latest_document_triggers_feature_extraction(monkeypatch):
    pipeline_calls: list = []
    project_id = uuid.uuid4()
    doc = _doc(project_id)
    project_id, ingestion = _install_fakes(
        monkeypatch, doc=doc, latest=doc, pipeline_calls=pipeline_calls
    )

    await w._run_job_async(str(doc.id), _embed=_SENTINEL, _llm=_SENTINEL)

    ingestion.ingest_document.assert_awaited_once()
    assert pipeline_calls == [(doc, _SENTINEL, _SENTINEL)]


@pytest.mark.asyncio
async def test_older_document_does_not_overwrite_feature_profile(monkeypatch):
    """Only the project's latest posting drives the feature profile."""
    pipeline_calls: list = []
    project_id = uuid.uuid4()
    doc = _doc(project_id)
    newer = _doc(project_id)
    project_id, ingestion = _install_fakes(
        monkeypatch, doc=doc, latest=newer, pipeline_calls=pipeline_calls
    )

    await w._run_job_async(str(doc.id), _embed=_SENTINEL, _llm=_SENTINEL)

    ingestion.ingest_document.assert_awaited_once()
    assert pipeline_calls == []


@pytest.mark.asyncio
async def test_missing_document_skips_extraction(monkeypatch):
    pipeline_calls: list = []
    project_id, ingestion = _install_fakes(
        monkeypatch, doc=None, latest=None, pipeline_calls=pipeline_calls
    )

    await w._run_job_async(str(uuid.uuid4()), _embed=_SENTINEL, _llm=_SENTINEL)

    ingestion.ingest_document.assert_awaited_once()
    assert pipeline_calls == []


@pytest.mark.asyncio
async def test_extraction_failure_never_fails_the_ingest(monkeypatch):
    """The ingest already succeeded; a broken extractor only logs."""
    pipeline_calls: list = []
    doc = _doc(uuid.uuid4())
    project_id, ingestion = _install_fakes(
        monkeypatch, doc=doc, latest=doc, pipeline_calls=pipeline_calls, pipeline_raises=True
    )

    await w._run_job_async(str(doc.id), _embed=_SENTINEL, _llm=_SENTINEL)

    ingestion.ingest_document.assert_awaited_once()
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0][1] is _SENTINEL
