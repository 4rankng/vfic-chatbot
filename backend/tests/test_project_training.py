"""One-file training persists its whole batch and resumes confirmed work."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.models.knowledge import KnowledgeCategoryRevisionStatus, KnowledgeDocument, KnowledgeStatus
from app.models.company import Project
from app.schemas.knowledge import KnowledgeDocumentOut, ProjectTrainingPlan
from app.services.knowledge.category_markdown import build_source_markdown
from app.services.knowledge.project_training import ProjectTrainingService, validate_training_plan
from app.services.knowledge.service import KnowledgeService
from app.services.knowledge.training_guard import ensure_training_owner
from app.shared.domain.errors import ConflictError, UpstreamError


def _write(key, records):
    return {
        "key": key,
        "filename": f"{key}.md",
        "content": build_source_markdown(
            {
                "schema_version": "1.0",
                "category": key,
                key: records,
            }
        ),
    }


def _plan():
    # Intentionally supplied in reverse dependency order.
    return ProjectTrainingPlan(
        writes=[
            _write(
                "compensation",
                [{"id": "pay", "job_ids": ["operator"], "base_salary_vnd": 6_000_000}],
            ),
            _write("jobs", [{"id": "operator", "title": "Công nhân"}]),
        ]
    )


def _doc():
    return KnowledgeDocument(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        file_name="brief.txt",
        source="upload",
        status=KnowledgeStatus.PROCESSING,
        stage="TRAINING_CATEGORIES",
        raw_text="Công nhân, lương 6.000.000 đồng",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        metadata_={
            "project_training": {
                **_plan().model_dump(mode="json"),
                "actor_id": str(uuid.uuid4()),
                "processing_token": str(uuid.uuid4()),
                "lease_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            }
        },
        digest_meta={"project_training": {"status": "PROCESSING", "completed": []}},
    )


def _categories(*, refuse_activation=False):
    revisions = {}
    calls = []

    async def stage(**kwargs):
        assert kwargs["schedule"] is False
        calls.append(kwargs["category_key"].value)
        revision = SimpleNamespace(id=uuid.uuid4(), status=KnowledgeCategoryRevisionStatus.STAGED)
        revisions[revision.id] = revision
        return revision, "receipt"

    async def activate(revision_id, _embedder, **kwargs):
        assert kwargs["training_document_id"]
        assert kwargs["training_token"]
        if not refuse_activation:
            revisions[revision_id].status = KnowledgeCategoryRevisionStatus.ACTIVE

    return SimpleNamespace(stage_replacement=stage, activate_revision=activate), calls, revisions


def _db(doc, *, newer_source=False, active_id=None):
    async def scalar(statement):
        description = statement.column_descriptions[0]
        if description["expr"] is KnowledgeDocument:
            return doc
        if description["entity"] is Project:
            return doc.project_id
        if getattr(description["expr"], "key", None) == "metadata_":
            return doc.metadata_
        if getattr(description["expr"], "key", None) == "active_revision_id":
            return active_id
        return uuid.uuid4() if newer_source else None

    db = AsyncMock()
    db.scalar.side_effect = scalar
    return db


def _service(db, doc, categories):
    return ProjectTrainingService(
        db,
        categories=categories,
        processing_token=uuid.UUID(doc.metadata_["project_training"]["processing_token"]),
    )


async def test_training_runs_every_category_on_the_worker_without_nested_queue():
    doc = _doc()
    db = _db(doc)
    categories, calls, _revisions = _categories()

    await _service(db, doc, categories).run(doc, object())

    assert calls == ["jobs", "compensation"]
    assert doc.digest_meta["project_training"] == {
        "status": "COMPLETED",
        "current": None,
        "completed": ["jobs", "compensation"],
        "error": None,
    }
    assert doc.stage == "PUBLISHED"
    assert doc.status == KnowledgeStatus.PUBLISHED
    assert set(doc.metadata_["project_training"]["revision_ids"]) == {"jobs", "compensation"}


async def test_training_retry_resumes_confirmed_checkpoint():
    doc = _doc()
    active_id = uuid.uuid4()
    doc.metadata_["project_training"]["revision_ids"] = {"jobs": str(active_id)}
    doc.digest_meta["project_training"]["completed"] = ["jobs"]
    db = _db(doc, active_id=active_id)
    categories, calls, _revisions = _categories()

    await _service(db, doc, categories).run(doc, object())

    assert calls == ["compensation"]
    assert doc.digest_meta["project_training"]["completed"] == ["jobs", "compensation"]


async def test_training_does_not_confirm_an_unactivated_revision():
    doc = _doc()
    db = _db(doc)
    categories, calls, _revisions = _categories(refuse_activation=True)

    with pytest.raises(ConflictError, match="not confirmed active"):
        await _service(db, doc, categories).run(doc, object())

    assert calls == ["jobs"]
    assert doc.digest_meta["project_training"]["completed"] == []


@pytest.mark.parametrize("newer_source", [True, False])
async def test_retry_cannot_overwrite_newer_source_or_manual_category_edit(newer_source):
    doc = _doc()
    doc.metadata_["project_training"]["revision_ids"] = {"jobs": str(uuid.uuid4())}
    doc.digest_meta["project_training"]["completed"] = ["jobs"]
    db = _db(doc, newer_source=newer_source, active_id=uuid.uuid4())
    categories, calls, _revisions = _categories()

    with pytest.raises(ConflictError):
        await _service(db, doc, categories).run(doc, object())
    assert calls == []


async def test_duplicate_delivery_does_not_run_while_lease_is_alive():
    db = AsyncMock()
    doc = _doc()
    doc.metadata_["project_training"]["lease_expires_at"] = (
        datetime.now(UTC) + timedelta(minutes=5)
    ).isoformat()
    db.scalar.return_value = doc

    assert await ProjectTrainingService(db).claim(doc) is False


async def test_late_duplicate_delivery_does_not_restart_completed_training():
    doc = _doc()
    doc.digest_meta["project_training"]["status"] = "COMPLETED"
    doc.metadata_["project_training"]["lease_expires_at"] = None
    assert await ProjectTrainingService(_db(doc)).claim(doc) is False


async def test_archived_source_cannot_be_claimed_by_a_late_delivery():
    doc = _doc()
    doc.status = KnowledgeStatus.ARCHIVED
    doc.metadata_["project_training"]["lease_expires_at"] = None
    assert await ProjectTrainingService(_db(doc)).claim(doc) is False


async def test_failed_worker_can_reclaim_a_source_without_waiting_for_lease():
    db = AsyncMock()
    doc = _doc()
    doc.stage = "FAILED"
    # Both async and outer-RQ crash handlers release the exact claimant's lease.
    doc.metadata_["project_training"]["lease_expires_at"] = None
    db.scalar.return_value = doc

    assert await ProjectTrainingService(db).claim(doc) is True
    assert doc.digest_meta["project_training"]["status"] == "PROCESSING"


@pytest.mark.parametrize("lost_ownership", ["expired", "reclaimed"])
async def test_checkpoint_rejects_expired_or_reclaimed_processing_token(lost_ownership):
    doc = _doc()
    previous_token = uuid.UUID(doc.metadata_["project_training"]["processing_token"])
    if lost_ownership == "expired":
        doc.metadata_["project_training"]["lease_expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    else:
        doc.metadata_["project_training"]["processing_token"] = str(uuid.uuid4())
    with pytest.raises(ConflictError, match="no longer owns"):
        await ensure_training_owner(_db(doc), doc.id, doc.project_id, previous_token)


def test_training_plan_rejects_duplicate_keys_and_bad_sibling_references():
    writes = _plan().model_dump(mode="json")["writes"]
    with pytest.raises(ValueError, match="repeat"):
        ProjectTrainingPlan(writes=[writes[0], writes[0]])
    writes[0] = _write("compensation", [{"id": "pay", "job_ids": ["invented-job"]}])
    with pytest.raises(ValueError, match="absent"):
        validate_training_plan(ProjectTrainingPlan(writes=writes))


def test_document_receipt_exposes_progress_without_the_retained_training_payload():
    doc = _doc()
    payload = KnowledgeDocumentOut.model_validate(doc).model_dump(mode="json")
    assert payload["project_training"]["status"] == "PROCESSING"
    assert "writes" not in payload["project_training"]
    assert "metadata_" not in payload
    assert "actor_id" not in payload["project_training"]


async def test_failed_source_retry_preserves_checkpoints_and_reports_queued_before_enqueue():
    doc = _doc()
    doc.metadata_["project_training"].update(processing_token=None, lease_expires_at=None)
    doc.digest_meta["project_training"].update(status="FAILED", completed=["jobs"], error="failed")
    doc.status = KnowledgeStatus.FAILED
    seen = []

    def enqueue(document_id):
        seen.append(document_id)
        assert doc.digest_meta["project_training"]["status"] == "QUEUED"
        assert doc.digest_meta["project_training"]["completed"] == ["jobs"]
        assert doc.error is None

    await KnowledgeService(_db(doc)).queue_document(doc, jobs=SimpleNamespace(ingest_document=enqueue))
    assert seen == [doc.id]


async def test_queue_outage_marks_retained_source_failed_without_losing_checkpoints():
    doc = _doc()
    doc.metadata_["project_training"].update(processing_token=None, lease_expires_at=None)
    doc.digest_meta["project_training"]["completed"] = ["jobs"]

    def unavailable(_document_id):
        raise RuntimeError("private provider detail")

    with pytest.raises(UpstreamError):
        await KnowledgeService(_db(doc)).queue_document(doc, jobs=SimpleNamespace(ingest_document=unavailable))
    assert doc.status == KnowledgeStatus.FAILED
    assert doc.digest_meta["project_training"]["status"] == "FAILED"
    assert doc.digest_meta["project_training"]["completed"] == ["jobs"]
    assert "private" not in doc.error


async def test_lost_queue_receipt_cannot_overwrite_already_completed_worker_state():
    doc = _doc()
    doc.metadata_["project_training"].update(processing_token=None, lease_expires_at=None)

    def accepted_but_receipt_lost(_document_id):
        doc.status = KnowledgeStatus.PUBLISHED
        doc.stage = "PUBLISHED"
        doc.digest_meta["project_training"].update(status="COMPLETED", completed=["jobs", "compensation"])
        raise RuntimeError("broker receipt lost")

    await KnowledgeService(_db(doc)).queue_document(doc, jobs=SimpleNamespace(ingest_document=accepted_but_receipt_lost))
    assert doc.status == KnowledgeStatus.PUBLISHED
    assert doc.digest_meta["project_training"]["status"] == "COMPLETED"
