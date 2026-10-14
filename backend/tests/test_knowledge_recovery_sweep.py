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
    """Records statements; scripted rows per scalars() call, rowcounts per execute().

    Mirrors ``AsyncSession`` faithfully: ``scalars()`` is a coroutine whose
    result carries ``.all()``. A synchronous fake returning ``SimpleNamespace``
    made missing-``await`` call sites valid, which is how the 2026-10-11
    production outage (``AttributeError: 'coroutine' object has no attribute
    'all'`` on every recovery tick) passed this suite.
    """

    def __init__(self, pages, rowcounts):
        self.pages = list(pages)
        self.rowcounts = list(rowcounts)
        self.rowcounts.reverse()  # execute() pops from the end
        self.executed = []
        self.selected = []
        self.commits = 0

    async def scalars(self, statement):
        self.selected.append(statement)
        rows = self.pages.pop(0)
        return SimpleNamespace(all=lambda: rows)

    async def execute(self, statement):
        self.executed.append(statement)
        return SimpleNamespace(rowcount=self.rowcounts.pop())

    async def commit(self):
        self.commits += 1


def _revision(*, status=KnowledgeCategoryRevisionStatus.PROCESSING):
    failed = status is KnowledgeCategoryRevisionStatus.FAILED
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        failure_code="category_retrieval_selftest_failed" if failed else None,
        error_message="boom" if failed else None,
        processing_token="tok",
        processing_started_at=PAST,
        lease_expires_at=FUTURE,
        quality_result={"project_training_document_id": str(uuid.uuid4()), "checksum": "x"},
    )


def _child(*, status=KnowledgeStatus.PROCESSING):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        stage="PREPARED",
        error=None,
        category_revision_id=uuid.uuid4(),
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
    inflight_revisions = [_revision(), _revision()]
    failed_revision = _revision(status=KnowledgeCategoryRevisionStatus.FAILED)
    prepared_children = [_child(), _child(status=KnowledgeStatus.FAILED)]
    fake = FakeSession(
        pages=[inflight_revisions + [failed_revision], prepared_children],
        rowcounts=[],
    )
    revision_count, child_count = await _abandon_training_batch(fake, doc)
    assert (revision_count, child_count) == (3, 2)
    assert doc.status is KnowledgeStatus.FAILED
    assert doc.digest_meta["project_training"]["status"] == "FAILED"
    assert doc.metadata_["project_training"]["lease_expires_at"] is None
    assert fake.commits == 1

    for revision in inflight_revisions:
        assert revision.status is KnowledgeCategoryRevisionStatus.FAILED
        assert revision.failure_code == TRAINING_RUN_ABANDONED_CODE
        assert revision.quality_result == {}
    assert failed_revision.status is KnowledgeCategoryRevisionStatus.FAILED
    assert failed_revision.failure_code == "category_retrieval_selftest_failed"
    assert failed_revision.quality_result == {}
    for child in prepared_children:
        assert child.category_revision_id is None
    for child in prepared_children[:1]:
        assert child.status is KnowledgeStatus.FAILED
        assert child.error is not None
    assert prepared_children[1].status is KnowledgeStatus.FAILED
    assert prepared_children[1].error is None


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


def test_full_sweep_completes_all_three_legs():
    """Regression (2026-10-11): the sweep must run to completion on an
    async-faithful session. The first statement died on every production tick
    (``db.scalars(...)`` coroutine awaited nowhere), so no leg ever ran and
    orphaned ingest work stayed stuck forever. An abandoned training doc drives
    leg 1 (its two artifact queries) plus the two bulk-update legs."""

    async def run():
        abandoned = _doc(status=KnowledgeStatus.PROCESSING, lease=PAST, updated=OLD)
        orphaned_revision = [_revision()]
        prepared_child = [_child()]
        fake = FakeSession(
            pages=[[abandoned], orphaned_revision, prepared_child],
            rowcounts=[7, 4],
        )
        counts = await recover_abandoned_ingest_work(fake)
        return counts, fake, abandoned, orphaned_revision, prepared_child

    counts, fake, abandoned, orphaned_revision, prepared_child = asyncio.run(run())
    # Leg 1 classified and abandoned exactly one training batch.
    assert counts["training_batches"] == 1
    assert abandoned.status is KnowledgeStatus.FAILED
    assert abandoned.metadata_["project_training"]["lease_expires_at"] is None
    assert orphaned_revision[0].failure_code == TRAINING_RUN_ABANDONED_CODE
    assert prepared_child[0].category_revision_id is None
    # Legs 2 and 3 still ran after leg 1's per-batch commit.
    assert len(fake.selected) == 3  # batches + revisions + children
    assert len(fake.executed) == 2  # orphan documents + orphan revisions updates
    assert fake.commits == 3  # one per abandoned batch + one per bulk leg
    assert counts["orphan_documents"] == 7
    assert counts["orphan_revisions"] == 4
