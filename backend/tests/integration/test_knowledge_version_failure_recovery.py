"""A database failure must leave retained KB versions retryable."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import literal, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.knowledge as knowledge_package
import app.project_knowledge.infrastructure.ingestion as ingestion_module
from app.models.company import Project
from app.models.knowledge import KBTextFile, KBVersion, KBVersionStatus, KnowledgeDocument
from app.services.knowledge.service import KnowledgeService
from app.project_knowledge.infrastructure.ingestion import SqlAlchemyKnowledgeIngestionAdapter

pytestmark = pytest.mark.integration


async def test_version_ingest_rolls_back_failed_sql_and_keeps_source_for_retry(
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
        version = KBVersion(project_id=project.id, version_no=1)
        document = KnowledgeDocument(
            project_id=project.id, file_name="brief.txt", raw_text="Có xe đưa đón."
        )
        db.add_all([version, document])
        await db.flush()
        source = KBTextFile(
            project_id=project.id, kb_version_id=version.id, document_id=document.id,
            filename="brief.txt", raw_text=document.raw_text,
            normalized_text=document.raw_text, content_sha256="a" * 64,
            char_count=len(document.raw_text), line_count=1,
        )
        db.add(source)
        await db.commit()
        version_id, source_id = version.id, source.id

        class FailedPipeline:
            def __init__(self, session, _embedder, _extractor):
                self.session = session

            async def run(self, _document):
                # PostgreSQL aborts the transaction, as a failed chunk write
                # would; failure receipt writes cannot proceed until rollback.
                await self.session.execute(select(literal(1) / literal(0)))

        monkeypatch.setattr(knowledge_package, "KnowledgePipeline", FailedPipeline)
        service = KnowledgeService(db)
        with pytest.raises(DBAPIError):
            await service.ingest_version(lambda _: None, version, llm_json=lambda *_: None)

        retained = await db.get(KBVersion, version_id, populate_existing=True)
        assert retained.status == KBVersionStatus.FAILED
        assert retained.error_message == "Chưa hoàn tất xử lý kiến thức. Vui lòng thử xử lý lại tệp đã lưu."
        retained_source = await db.get(KBTextFile, source_id)
        assert retained_source.normalized_text == "Có xe đưa đón."

        class SuccessfulPipeline(FailedPipeline):
            async def run(self, _document):
                return None

        monkeypatch.setattr(knowledge_package, "KnowledgePipeline", SuccessfulPipeline)
        retried = await service.ingest_version(
            lambda _: None, retained, llm_json=lambda *_: None,
        )
        assert retried.status == KBVersionStatus.READY
        assert retried.error_message is None


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
        version = KBVersion(project_id=project.id, version_no=1)
        db.add(version)
        await db.commit()
        version_id = version.id

        class Settings:
            def __init__(self, _db):
                pass

            async def resolve_embedding(self):
                if failure_phase == "provider_configuration":
                    raise ValueError("private provider response secret-key candidate-content")
                return SimpleNamespace()

        class Service:
            def __init__(self, session):
                self.session = session

            async def ingest_version(self, *_args, **_kwargs):
                await self.session.execute(select(literal(1) / literal(0)))

        monkeypatch.setattr(ingestion_module, "IntegrationSettingsService", Settings)
        monkeypatch.setattr(ingestion_module, "KnowledgeService", Service)
        worker = SqlAlchemyKnowledgeIngestionAdapter(db, providers=SimpleNamespace())
        await worker.ingest_version(
            version_id, embedder=lambda _: None, json_extractor=lambda *_: None,
        )
        retained = await db.get(KBVersion, version_id, populate_existing=True)
        assert retained.status == KBVersionStatus.FAILED
        assert retained.error_message == "Chưa hoàn tất xử lý kiến thức. Vui lòng thử xử lý lại tệp đã lưu."
        assert "secret-key" not in caplog.text
        assert "candidate-content" not in caplog.text
