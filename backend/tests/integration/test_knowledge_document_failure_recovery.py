"""A database failure must leave retained knowledge sources retryable."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.project_knowledge.infrastructure.ingestion as ingestion_module
from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.project_knowledge.infrastructure.ingestion import SqlAlchemyKnowledgeIngestionAdapter

pytestmark = pytest.mark.integration


async def test_document_ingest_rolls_back_failed_sql_and_keeps_source_for_retry(
    integration_session, monkeypatch,
) -> None:
    # Production rollback must preserve previously committed setup. The outer
    # fixture transaction still owns all rows through this session's savepoints.
    async with AsyncSession(
        bind=integration_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as db:
        project = Project(slug=f"recover-{uuid.uuid4().hex[:8]}", name="Dự án thử lại")
        db.add(project)
        await db.flush()
        document = KnowledgeDocument(
            project_id=project.id,
            file_name="brief.txt",
            raw_text="Có xe đưa đón.",
        )
        db.add(document)
        await db.commit()
        document_id = document.id

        class FailedPipeline:
            def __init__(self, session, _embedder, _extractor):
                self.session = session

            async def run(self, _doc):
                # PostgreSQL aborts the transaction, as a failed chunk write
                # would; failure receipt writes cannot proceed until rollback.
                await self.session.execute(select(literal(1) / literal(0)))

        monkeypatch.setattr(ingestion_module, "KnowledgePipeline", FailedPipeline)
        worker = SqlAlchemyKnowledgeIngestionAdapter(db, providers=SimpleNamespace())
        await worker.ingest_document(
            document_id, embedder=lambda _: None, json_extractor=lambda *_: None,
        )

        retained = await db.get(KnowledgeDocument, document_id, populate_existing=True)
        assert retained.status == KnowledgeStatus.FAILED
        assert retained.error == "Chưa hoàn tất xử lý kiến thức. Vui lòng thử xử lý lại tệp đã lưu."
        assert retained.raw_text == "Có xe đưa đón."

        class SuccessfulPipeline(FailedPipeline):
            async def run(self, doc):
                doc.status = KnowledgeStatus.PUBLISHED
                doc.error = None
                await self.session.commit()

        monkeypatch.setattr(ingestion_module, "KnowledgePipeline", SuccessfulPipeline)
        await worker.ingest_document(
            document_id, embedder=lambda _: None, json_extractor=lambda *_: None,
        )
        retried = await db.get(KnowledgeDocument, document_id, populate_existing=True)
        assert retried.status == KnowledgeStatus.PUBLISHED
        assert retried.error is None


@pytest.mark.parametrize("failure_phase", ["provider_configuration", "database_write"])
async def test_worker_records_configuration_and_database_failures_without_sensitive_errors(
    integration_session, monkeypatch, caplog, failure_phase,
) -> None:
    async with AsyncSession(
        bind=integration_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as db:
        project = Project(slug=f"worker-{uuid.uuid4().hex[:8]}", name="Dự án thử lại")
        db.add(project)
        await db.flush()
        document = KnowledgeDocument(
            project_id=project.id, file_name="brief.txt", raw_text="Nội dung."
        )
        db.add(document)
        await db.commit()
        document_id = document.id

        class Settings:
            def __init__(self, _db):
                pass

            async def resolve_embedding(self):
                if failure_phase == "provider_configuration":
                    raise ValueError("private provider response secret-key candidate-content")
                return SimpleNamespace()

        class FailedPipeline:
            def __init__(self, session, _embedder, _extractor):
                self.session = session

            async def run(self, _doc):
                await self.session.execute(select(literal(1) / literal(0)))

        monkeypatch.setattr(ingestion_module, "IntegrationSettingsService", Settings)
        monkeypatch.setattr(ingestion_module, "KnowledgePipeline", FailedPipeline)
        worker = SqlAlchemyKnowledgeIngestionAdapter(db, providers=SimpleNamespace())
        await worker.ingest_document(
            document_id, embedder=lambda _: None, json_extractor=lambda *_: None,
        )
        retained = await db.get(KnowledgeDocument, document_id, populate_existing=True)
        assert retained.status == KnowledgeStatus.FAILED
        assert retained.error == "Chưa hoàn tất xử lý kiến thức. Vui lòng thử xử lý lại tệp đã lưu."
        assert "secret-key" not in caplog.text
        assert "candidate-content" not in caplog.text
