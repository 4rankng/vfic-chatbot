"""Integration: the knowledge recovery sweep completes against a real AsyncSession.

Regression for the 2026-10-11 production outage: the sweep's first statement
called ``.all()`` on the coroutine returned by ``AsyncSession.scalars`` and
died with ``AttributeError`` on EVERY tick for three days — orphaned ingest
work accumulated with no recovery path. The unit suite missed it because its
fake session exposed a *synchronous* ``scalars``; this lane runs the sweep
through real asyncpg so a missing ``await`` cannot pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.models.company import Project
from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.services.knowledge.recovery_sweep import (
    INGEST_INTERRUPTED_MESSAGE,
    TRAINING_RUN_INTERRUPTED_MESSAGE,
    recover_abandoned_ingest_work,
)

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=3)
FRESH = NOW - timedelta(minutes=10)
FUTURE_LEASE = (NOW + timedelta(hours=1)).isoformat()
PAST_LEASE = (NOW - timedelta(hours=1)).isoformat()


def _training_doc(project_id, *, lease_iso, updated) -> KnowledgeDocument:
    return KnowledgeDocument(
        file_name=f"training-{uuid.uuid4().hex[:6]}.md",
        source="upload",
        status=KnowledgeStatus.PROCESSING,
        stage="TRAINING",
        project_id=project_id,
        updated_at=updated,
        metadata_={"project_training": {"status": "PROCESSING", "lease_expires_at": lease_iso}},
        digest_meta={"project_training": {"status": "PROCESSING", "completed": []}},
    )


@pytest.mark.asyncio
async def test_sweep_recovers_all_legs_on_a_real_session(integration_session) -> None:
    project = Project(slug=f"recovery-{uuid.uuid4().hex[:8]}", name="Recovery Co")
    integration_session.add(project)
    await integration_session.flush()

    # Abandoned training batch: expired lease, untouched for days.
    abandoned = _training_doc(project.id, lease_iso=PAST_LEASE, updated=OLD)
    # Live training batch: lease still in the future — must stay untouched.
    live_training = _training_doc(project.id, lease_iso=FUTURE_LEASE, updated=FRESH)
    # Prepared child of the abandoned batch: PROCESSING, links to the dead run.
    child = KnowledgeDocument(
        file_name=f"child-{uuid.uuid4().hex[:6]}.md",
        source="upload",
        status=KnowledgeStatus.PROCESSING,
        stage="PREPARED",
        project_id=project.id,
        updated_at=OLD,
        metadata_={"project_training_document_id": None},
    )
    integration_session.add_all([abandoned, live_training, child])
    await integration_session.flush()
    child.metadata_ = {"project_training_document_id": str(abandoned.id)}

    # Plain orphan document: in-flight long past twice the RQ job budget.
    orphan = KnowledgeDocument(
        file_name=f"orphan-{uuid.uuid4().hex[:6]}.txt",
        source="upload",
        status=KnowledgeStatus.PROCESSING,
        stage="PROCESSING",
        updated_at=OLD,
    )
    # Plain live document: recent activity — must stay untouched.
    live_plain = KnowledgeDocument(
        file_name=f"live-{uuid.uuid4().hex[:6]}.txt",
        source="upload",
        status=KnowledgeStatus.PROCESSING,
        stage="PROCESSING",
        updated_at=FRESH,
    )
    integration_session.add_all([orphan, live_plain])
    await integration_session.commit()

    # Precondition: the child really is reachable only through the sweep.
    stored_child = await integration_session.get(KnowledgeDocument, child.id)
    assert stored_child.status is KnowledgeStatus.PROCESSING

    counts = await recover_abandoned_ingest_work(integration_session)

    assert counts["training_batches"] == 1
    assert counts["orphan_documents"] == 1

    # The two bulk-update legs bypass the identity map; refresh before reading.
    for row in (abandoned, child, orphan, live_training, live_plain):
        await integration_session.refresh(row)

    failed_batch = await integration_session.get(KnowledgeDocument, abandoned.id)
    assert failed_batch.status is KnowledgeStatus.FAILED
    assert failed_batch.error == TRAINING_RUN_INTERRUPTED_MESSAGE
    assert failed_batch.metadata_["project_training"]["lease_expires_at"] is None

    failed_child = await integration_session.get(KnowledgeDocument, child.id)
    assert failed_child.status is KnowledgeStatus.FAILED
    assert failed_child.error == TRAINING_RUN_INTERRUPTED_MESSAGE

    failed_orphan = await integration_session.get(KnowledgeDocument, orphan.id)
    assert failed_orphan.status is KnowledgeStatus.FAILED
    assert failed_orphan.error == INGEST_INTERRUPTED_MESSAGE

    # Live work was not disturbed.
    untouched_training = await integration_session.get(KnowledgeDocument, live_training.id)
    assert untouched_training.status is KnowledgeStatus.PROCESSING
    untouched_plain = await integration_session.get(KnowledgeDocument, live_plain.id)
    assert untouched_plain.status is KnowledgeStatus.PROCESSING
