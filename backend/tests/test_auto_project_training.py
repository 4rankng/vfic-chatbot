"""Automatic extraction persists progress without exposing partial category writes."""

import hashlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.services.knowledge import extraction
from app.services.knowledge.canonical import checksum_text
from app.services.knowledge.category_batch import TrainingCategoryBatch
from app.services.knowledge.category_markdown import build_source_markdown
from app.services.knowledge.project_training import ProjectTrainingService
from app.schemas.knowledge import ProjectTrainingPlan
from app.shared.domain.errors import ConflictError


def _source():
    return KnowledgeDocument(
        id=uuid.uuid4(), project_id=uuid.uuid4(), raw_text="Tuyển công nhân.",
        file_name="brief.txt", source="upload", stage="EXTRACTED",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        status=KnowledgeStatus.PROCESSING,
        metadata_={"project_training": {"auto_extract": True, "writes": []}},
        digest_meta={"project_training": {"status": "PROCESSING", "completed": []}},
    )


def _checkpoint(doc, *, status="COMPLETED"):
    return {
        "version": extraction.CATEGORY_PLAN_VERSION,
        "source_sha256": hashlib.sha256(doc.raw_text.encode()).hexdigest(),
        "status": status, "total_sections": 1, "completed_sections": 1,
        "sections": [], "covered_categories": ["jobs"], "missing_categories": ["meals"],
    }


def _plan():
    return ProjectTrainingPlan(writes=[{
        "key": "jobs", "filename": "jobs.md", "content": build_source_markdown({
            "schema_version": "1.0", "category": "jobs", "jobs": [{"id": "operator", "title": "Công nhân"}],
        }),
    }])


def _service():
    db = AsyncMock()
    batch = SimpleNamespace(check_extraction_baseline=AsyncMock())
    service = ProjectTrainingService(db, categories=SimpleNamespace(), batch=batch)
    service._guard = AsyncMock()
    return service, db, batch


async def test_worker_saves_extraction_checkpoint_before_retaining_validated_plan(monkeypatch):
    doc = _source()
    service, db, batch = _service()
    plan = _plan()

    async def extract(text, llm_json, *, checkpoint, on_checkpoint):
        assert text == doc.raw_text
        assert checkpoint is None
        assert doc.stage == "EXTRACTING_CATEGORIES"
        await on_checkpoint(_checkpoint(doc))
        assert doc.metadata_["project_training"]["writes"] == []
        assert doc.digest_meta["project_training"]["source_sections_completed"] == 1
        return plan

    monkeypatch.setattr(extraction, "extract_category_plan", extract)
    await service.prepare_plan(doc, AsyncMock())
    training = doc.metadata_["project_training"]
    assert training["writes"] == plan.model_dump(mode="json")["writes"]
    assert training["extracted_plan_sha256"] == checksum_text(plan.model_dump_json())
    assert doc.digest_meta["project_training"]["planned"] == ["jobs"]
    assert doc.digest_meta["project_training"]["completed"] == []
    assert db.commit.await_count == 3
    assert batch.check_extraction_baseline.await_count == 3


async def test_failed_extraction_retains_checkpoint_and_reuses_it_on_retry(monkeypatch):
    doc = _source()
    service, _db, _batch = _service()
    partial = _checkpoint(doc, status="PROCESSING")

    async def failing(_text, _llm, *, checkpoint, on_checkpoint):
        await on_checkpoint(partial)
        raise extraction.CategoryPlanExtractionError("Không thể trích xuất danh mục.")

    monkeypatch.setattr(extraction, "extract_category_plan", failing)
    with pytest.raises(extraction.CategoryPlanExtractionError):
        await service.prepare_plan(doc, AsyncMock())
    assert doc.metadata_["project_training"]["writes"] == []
    assert doc.metadata_["project_training"]["extraction"] == partial

    async def resumed(_text, _llm, *, checkpoint, on_checkpoint):
        assert checkpoint == partial
        await on_checkpoint(_checkpoint(doc))
        return _plan()

    monkeypatch.setattr(extraction, "extract_category_plan", resumed)
    await service.prepare_plan(doc, AsyncMock())
    assert len(doc.metadata_["project_training"]["writes"]) == 1


async def test_source_without_category_facts_fails_without_silent_plain_ingest(monkeypatch):
    doc = _source()
    service, _db, _batch = _service()
    monkeypatch.setattr(extraction, "extract_category_plan", AsyncMock(return_value=None))
    with pytest.raises(extraction.CategoryPlanExtractionError, match="chưa có thông tin"):
        await service.prepare_plan(doc, AsyncMock())
    assert doc.metadata_["project_training"]["writes"] == []


@pytest.mark.parametrize("changed", ["source", "plan", "incomplete"])
async def test_saved_plan_cannot_bypass_source_and_plan_integrity(changed, monkeypatch):
    doc = _source()
    service, _db, _batch = _service()
    training = doc.metadata_["project_training"]
    plan = _plan()
    training.update(
        writes=plan.model_dump(mode="json")["writes"], extraction=_checkpoint(doc),
        extracted_plan_sha256=checksum_text(plan.model_dump_json()),
    )
    if changed == "source":
        doc.raw_text += " Nội dung thay đổi."
    elif changed == "plan":
        training["extracted_plan_sha256"] = "wrong"
    else:
        training["extraction"]["status"] = "PROCESSING"
    extract = AsyncMock()
    monkeypatch.setattr(extraction, "extract_category_plan", extract)
    with pytest.raises(extraction.CategoryPlanExtractionError, match="không còn khớp"):
        await service.prepare_plan(doc, AsyncMock())
    extract.assert_not_awaited()


async def test_category_baseline_uses_own_staged_checkpoint_but_rejects_later_edits():
    doc = _source()
    category = SimpleNamespace(id=uuid.uuid4(), category_key="jobs", active_revision_id=None)
    doc.metadata_["project_training"].update(
        extraction_baseline={"jobs": {"active": None, "latest": 0}},
        batch_snapshot={"jobs": {"active": None, "latest": 1}},
    )
    batch = TrainingCategoryBatch(AsyncMock(), SimpleNamespace(), uuid.uuid4())
    batch._lock = AsyncMock(return_value=([category], {category.id: 1}))
    await batch.check_extraction_baseline(doc)
    batch._lock.return_value = ([category], {category.id: 2})
    with pytest.raises(ConflictError):
        await batch.check_extraction_baseline(doc)


@pytest.mark.parametrize("explicit_plan", [False, True])
async def test_upload_returns_retained_source_without_resolving_an_extraction_provider(
    monkeypatch, explicit_plan
):
    from app.api import knowledge
    from app.services.integration_settings import IntegrationSettingsService

    source = _source()
    data = "Tuyển công nhân.".encode("utf-16")
    db = AsyncMock()
    actor = SimpleNamespace(id=uuid.uuid4())
    file = SimpleNamespace(filename="brief.txt", content_type="text/plain")
    service = SimpleNamespace(upload_bytes=AsyncMock(return_value=source))
    monkeypatch.setattr(knowledge, "KnowledgeService", lambda _db: service)
    monkeypatch.setattr(knowledge, "read_upload_within_limit", AsyncMock(return_value=data))
    monkeypatch.setattr(knowledge, "record_audit_safe", AsyncMock())
    queued = AsyncMock()
    monkeypatch.setattr(knowledge, "_queue_document", queued)
    resolve = AsyncMock()
    monkeypatch.setattr(IntegrationSettingsService, "resolve_minimax", resolve)
    plan = _plan() if explicit_plan else None
    result = await knowledge.upload_file(
        file=file, project_id=source.project_id,
        category_plan=plan.model_dump_json() if plan else None,
        auto_extract=True, _admin=actor, db=db,
    )
    service.upload_bytes.assert_awaited_once_with(
        file.filename, file.content_type, data, project_id=source.project_id,
        training_plan=plan, auto_extract=not explicit_plan, actor=actor,
    )
    queued.assert_awaited_once_with(source, db, reuse_completed=True)
    resolve.assert_not_awaited()
    assert result.id == source.id
