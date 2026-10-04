"""Recovery sweep tests: orphaned ingest artifacts get failed, live work is untouched."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import uuid

import pytest

from app.models.knowledge import KnowledgeCategoryRevisionStatus, KnowledgeStatus
from app.services.knowledge.recovery_sweep import (
    INGEST_INTERRUPTED_MESSAGE,
    PROCESSING_LEASE_EXPIRED_CODE,
    TRAINING_RUN_ABANDONED_CODE,
    _abandon_training_batch,
    recover_abandoned_ingest_work,
    training_batch_state,
)

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=3)
FRESH = NOW - timedelta(minutes=10)
FUTURE = NOW + timedelta(minutes=65)
PAST = NOW - timedelta(hours=1)


def _doc(*, status=KnowledgeStatus.PROCESSING, lease=FUTURE, updated=OLD):
    lease_iso = lease.isoformat() if isinstance(lease, datetime) else lease
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status=status,
        updated_at=updated,
        metadata_={"project_training": {"lease_expires_at": lease_iso}},
        digest_meta={"project_training": {"status": "PROCESSING", "completed": []}},
    )


class FakeSession:
    """Records statements; scripted rows per scalars() call, rowcounts per execute()."""

    def __init__(self, pages, rowcounts):
        self.pages = list(pages)
        self.rowcounts = list(rowcounts)
        self.rowcounts.reverse()  # execute() pops from the end
        self.executed = []
        self.selected = []
        self.commits = 0

    def scalars(self, statement):
        self.selected.append(statement)
        rows = self.pages.pop(0)
        return SimpleNamespace(all=lambda: rows)

    async def execute(self, statement):
        self.executed.append(statement)
        return SimpleNamespace(rowcount=self.rowcounts.pop())

    async def commit(self):
        self.commits += 1


def _revision():
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=KnowledgeCategoryRevisionStatus.PROCESSING,
        failure_code=None,
        error_message=None,
        processing_token="tok",
        processing_started_at=PAST,
        lease_expires_at=FUTURE,
        quality_result={"project_training_document_id": str(uuid.uuid4()), "checksum": "x"},
    )


def _child():
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=KnowledgeStatus.PROCESSING,
        stage="PREPARED",
        error=None,
    )


@pytest.mark.parametrize(
    ("meta", "status", "updated", "expected"),
    [
        (None, KnowledgeStatus.FAILED, OLD, "complete"),
        ({"status": "COMPLETED"}, KnowledgeStatus.PUBLISHED, OLD, "complete"),
        (
            {"lease_expires_at": FUTURE.isoformat()},
            KnowledgeStatus.ARCHIVED,
            OLD,
            "complete",
        ),
        ({"lease_expires_at": FUTURE.isoformat()}, KnowledgeStatus.PROCESSING, OLD, "owned"),
        ({"lease_expires_at": PAST.isoformat()}, KnowledgeStatus.PROCESSING, FRESH, "owned"),
        ({"lease_expires_at": PAST.isoformat()}, KnowledgeStatus.PROCESSING, OLD, "abandoned"),
        (None, KnowledgeStatus.PROCESSING, OLD, "complete"),
        ({"lease_expires_at": "not-a-date"}, KnowledgeStatus.PROCESSING, OLD, "abandoned"),
        ({"lease_expires_at": None}, KnowledgeStatus.PROCESSING, OLD, "abandoned"),
    ],
)
def test_training_batch_state(meta, status, updated, expected):
    assert training_batch_state(meta, status, updated, NOW) == expected


@pytest.mark.asyncio
async def test_abandon_training_batch():
    doc = _doc(status=KnowledgeStatus.PROCESSING, lease=PAST, updated=OLD)
    revisions = [_revision(), _revision()]
    children = [_child(), _child()]
    fake = FakeSession(pages=[[revisions[0], revisions[1]], [children[0], children[1]]], rowcounts=[])
    revision_count, child_count = await _abandon_training_batch(fake, doc)
    assert (revision_count, child_count) == (2, 2)

    assert doc.status is KnowledgeStatus.FAILED
    assert doc.stage == "FAILED"
    assert "bị gián đoạn" in doc.error
    assert doc.digest_meta["project_training"]["status"] == "FAILED"
    assert doc.metadata_["project_training"]["lease_expires_at"] is None
    assert fake.commits == 1

    for revision in revisions:
        assert revision.status is KnowledgeCategoryRevisionStatus.FAILED
        assert revision.failure_code == TRAINING_RUN_ABANDONED_CODE
        assert set(revision.quality_result) == {"project_training_document_id"}
    for child in children:
        assert child.status is KnowledgeStatus.FAILED
        assert child.error == doc.error


def test_bulk_update_targets_orphans():
    fake = FakeSession(pages=[[]], rowcounts=[7, 4])
    counts = asyncio.run(recover_abandoned_ingest_work(fake))
    assert len(fake.executed) == 2
    stmt_docs, stmt_revs = fake.executed
    assert stmt_docs.table.name == "knowledge_documents"
    assert stmt_revs.table.name == "knowledge_category_revisions"
    assert INGEST_INTERRUPTED_MESSAGE in stmt_docs.compile().params.values()
    assert PROCESSING_LEASE_EXPIRED_CODE in stmt_revs.compile().params.values()
    assert counts == {
        "training_batches": 0,
        "training_revisions": 0,
        "training_documents": 0,
        "orphan_documents": 7,
        "orphan_revisions": 4,
    }
