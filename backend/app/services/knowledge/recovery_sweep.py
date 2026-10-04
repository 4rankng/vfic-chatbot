"""Recovery sweep for knowledge-ingest work orphaned by dead workers.

The knowledge pipeline runs on RQ. A deploy or a crash kills
``worker-ingest``/``worker-category`` mid-job; the queue forgets the job and
nothing owns the in-flight document/revision rows afterwards, so they sit in
their in-flight states forever. Chat turns recover through
``reconcile_worker``; this module is the same idea for the knowledge pipeline.

States and the evidence that decides them:

- A training run owns its batch through ``metadata_.project_training``. Its
  lease (``TRAINING_LEASE_SECONDS`` = 3900s) always outlives the RQ job
  budget (``INGEST_JOB_TIMEOUT_SECONDS`` = 3600s), so an expired lease proves
  the run is dead. Between a successful prepare and the final publish a
  revision legitimately sits in PROCESSING with its claim stamps cleared
  (``TrainingCategoryBatch.prepare``), so revision stamps alone cannot tell
  mid-run from abandoned — the training lease is the discriminator. A
  gracefully failed run clears its lease and marks the document FAILED; the
  batch stays cheap-resumable for a grace window (its prepared evidence lets
  a retry skip re-embedding), after which the sweep declares it abandoned and
  drops the evidence.
- A plain (non-training) document is in-flight only while its RQ job lives.
  RQ kills any job at ``INGEST_JOB_TIMEOUT_SECONDS`` and its death penalty
  records FAILED, so a document still in-flight past twice that budget is
  provably orphaned.
- A non-training revision claimed by ``activate_revision`` always carries a
  lease and a processing timestamp; expired lease plus a spent time budget
  means the claiming worker is gone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)

logger = logging.getLogger(__name__)

# Operator-facing text shared with the RQ crash handler in ingest_worker.
INGEST_INTERRUPTED_MESSAGE = (
    "Tiến trình xử lý bị gián đoạn. Vui lòng thử xử lý lại tệp đã lưu."
)
# A training document interrupted mid-run reads slightly differently from a
# plain upload: the whole project batch stopped with it.
TRAINING_RUN_INTERRUPTED_MESSAGE = (
    "Quá trình nạp kiến thức dự án bị gián đoạn. Vui lòng thử xử lý lại tệp đã lưu."
)

# Stable failure codes (column limit 64), mirroring category_service's codes.
TRAINING_RUN_ABANDONED_CODE = "training_run_abandoned"
TRAINING_RUN_ABANDONED_MESSAGE = (
    "Training run interrupted before the category batch was published"
)
PROCESSING_LEASE_EXPIRED_CODE = "processing_lease_expired"
PROCESSING_LEASE_EXPIRED_MESSAGE = "Category processing worker died before finishing"

# A gracefully failed training batch stays cheap-resumable for a day: the
# prepared evidence (per-category documents still PROCESSING) lets the
# "process the saved file again" retry skip re-embedding. Past the window the
# batch is declared abandoned and its evidence is cleared, so a retry
# re-prepares every category from its staged markdown.
ABANDONED_TRAINING_GRACE_SECONDS = 86_400

# Document states the sweep treats as in-flight.
_INFLIGHT_DOC_STATUSES = (KnowledgeStatus.UPLOADED, KnowledgeStatus.PROCESSING)
_INFLIGHT_REVISION_STATUSES = (
    KnowledgeCategoryRevisionStatus.STAGED,
    KnowledgeCategoryRevisionStatus.PROCESSING,
)


def _ingest_orphan_cutoff(now: datetime) -> datetime:
    """Twice the RQ ingest budget — past this, no live job can still hold a row."""
    from app.core.config import INGEST_JOB_TIMEOUT_SECONDS

    return now - timedelta(seconds=2 * INGEST_JOB_TIMEOUT_SECONDS)


def training_batch_state(
    training_meta: dict[str, Any] | None,
    doc_status: KnowledgeStatus,
    updated_at: datetime | None,
    now: datetime,
    *,
    grace_seconds: int = ABANDONED_TRAINING_GRACE_SECONDS,
) -> str:
    """Classify a training document's batch: ``owned``, ``complete``, ``abandoned``.

    ``owned`` covers both a live lease and the post-failure grace window — the
    sweep leaves those alone because a retry can still resume them cheaply.
    ``abandoned`` requires no (or an expired) lease, an unfinished run, and a
    document untouched past the grace window; ``updated_at`` anchors the
    window because it is the last time anything — run or failure handler —
    touched the document.
    """
    if training_meta is None:
        return "complete"
    if training_meta.get("status") == "COMPLETED":
        return "complete"
    if doc_status is KnowledgeStatus.ARCHIVED:
        return "complete"
    lease = training_meta.get("lease_expires_at")
    if lease:
        try:
            if datetime.fromisoformat(str(lease)) > now:
                return "owned"
        except ValueError:
            pass  # An unparsable lease cannot vouch for a live run.
    if updated_at is None or updated_at > now - timedelta(seconds=grace_seconds):
        return "owned"
    return "abandoned"


async def recover_abandoned_ingest_work(db: AsyncSession) -> dict[str, int]:
    """Fail every orphaned knowledge-ingest artifact; returns per-kind counts.

    Each sweep leg commits separately so one failure cannot block the others.
    """
    now = datetime.now(UTC)
    counts = {
        "training_batches": 0,
        "training_revisions": 0,
        "training_documents": 0,
        "orphan_documents": 0,
        "orphan_revisions": 0,
    }
    counts["training_batches"] = await _sweep_abandoned_training_batches(db, now)
    counts["orphan_documents"] = await _sweep_orphan_documents(db, now)
    counts["orphan_revisions"] = await _sweep_orphan_revisions(db, now)
    return counts


async def _sweep_abandoned_training_batches(db: AsyncSession, now: datetime) -> int:
    """Declare expired training batches abandoned and fail their artifacts."""
    docs = (
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.project_id.is_not(None),
                KnowledgeDocument.metadata_["project_training"].is_not(None),
                KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
            )
        )
    ).all()
    batches = 0
    for doc in docs:
        state = training_batch_state(
            (doc.metadata_ or {}).get("project_training"),
            doc.status,
            doc.updated_at,
            now,
        )
        if state != "abandoned":
            continue
        batches += 1
        revisions, children = await _abandon_training_batch(db, doc)
        logger.warning(
            "knowledge recovery: training batch abandoned document_id=%s "
            "failed_revisions=%d failed_documents=%d",
            doc.id,
            revisions,
            children,
        )
    return batches


async def _abandon_training_batch(db: AsyncSession, doc: KnowledgeDocument) -> tuple[int, int]:
    """Fail one dead batch's artifacts and strip every trace of its ownership.

    Abandonment must leave the batch's artifacts in a plain-FAILED state with
    no special guards attached, or the standard repair affordances stay
    blocked forever:

    - Revisions lose their ``quality_result`` entirely (the ownership key it
      carries makes ``stage``/``activate_revision`` refuse per-category
      repair). FAILED revisions of the batch keep their original failure
      code/message — that is truthful history — but lose the key too.
    - Prepared child documents fail like any in-flight document AND release
      the ``category_revision_id`` link: the link backs a unique constraint,
      so a surviving link makes any later activation of that revision die on
      a duplicate-key error (the meals deadlock of 04–05 Oct).
    """
    training = dict((doc.metadata_ or {}).get("project_training") or {})
    if doc.status in _INFLIGHT_DOC_STATUSES:
        doc.status = KnowledgeStatus.FAILED
        doc.stage = "FAILED"
        doc.error = TRAINING_RUN_INTERRUPTED_MESSAGE
        progress = dict((doc.digest_meta or {}).get("project_training") or {})
        doc.digest_meta = {
            **(doc.digest_meta or {}),
            "project_training": {**progress, "status": "FAILED", "error": doc.error},
        }
        doc.metadata_ = {
            **(doc.metadata_ or {}),
            "project_training": {
                **training,
                "processing_token": None,
                "lease_expires_at": None,
            },
        }
    revisions = (
        db.scalars(
            select(KnowledgeCategoryRevision).where(
                KnowledgeCategoryRevision.quality_result["project_training_document_id"].astext
                == str(doc.id),
                KnowledgeCategoryRevision.status.in_(
                    [*_INFLIGHT_REVISION_STATUSES, KnowledgeCategoryRevisionStatus.FAILED]
                ),
            )
        )
    ).all()
    for revision in revisions:
        if revision.status in _INFLIGHT_REVISION_STATUSES:
            revision.status = KnowledgeCategoryRevisionStatus.FAILED
            revision.failure_code = TRAINING_RUN_ABANDONED_CODE
            revision.error_message = TRAINING_RUN_ABANDONED_MESSAGE
            revision.processing_token = None
            revision.processing_started_at = None
            revision.lease_expires_at = None
        revision.quality_result = {}
    children = (
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.metadata_["project_training_document_id"].astext == str(doc.id),
                KnowledgeDocument.status.in_(
                    [*_INFLIGHT_DOC_STATUSES, KnowledgeStatus.FAILED]
                ),
            )
        )
    ).all()
    for child in children:
        child.category_revision_id = None
        if child.status in _INFLIGHT_DOC_STATUSES:
            child.status = KnowledgeStatus.FAILED
            child.stage = "FAILED"
            child.error = TRAINING_RUN_INTERRUPTED_MESSAGE
    await db.commit()
    return len(revisions), len(children)


async def _sweep_orphan_documents(db: AsyncSession, now: datetime) -> int:
    """Fail plain documents whose ingest job is provably gone."""
    cutoff = _ingest_orphan_cutoff(now)
    result = await db.execute(
        update(KnowledgeDocument)
        .where(
            KnowledgeDocument.status.in_(_INFLIGHT_DOC_STATUSES),
            KnowledgeDocument.metadata_["project_training"].is_(None),
            KnowledgeDocument.metadata_["project_training_document_id"].is_(None),
            KnowledgeDocument.updated_at < cutoff,
        )
        .values(
            status=KnowledgeStatus.FAILED,
            stage="FAILED",
            error=INGEST_INTERRUPTED_MESSAGE,
            updated_at=now,
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


async def _sweep_orphan_revisions(db: AsyncSession, now: datetime) -> int:
    """Fail non-training revisions whose claiming worker is provably gone.

    Training-owned revisions are excluded here — the batch sweep above owns
    their lifecycle, and their post-prepare PROCESSING state carries no lease
    to judge freshness by.
    """
    cutoff = _ingest_orphan_cutoff(now)
    result = await db.execute(
        update(KnowledgeCategoryRevision)
        .where(
            KnowledgeCategoryRevision.status == KnowledgeCategoryRevisionStatus.PROCESSING,
            KnowledgeCategoryRevision.quality_result["project_training_document_id"].is_(None),
            KnowledgeCategoryRevision.processing_started_at.is_not(None),
            KnowledgeCategoryRevision.processing_started_at < cutoff,
            # The claim stamps a lease; a still-running worker keeps it in the
            # future, so only NULL (never stamped) or expired means orphaned.
            or_(
                KnowledgeCategoryRevision.lease_expires_at.is_(None),
                KnowledgeCategoryRevision.lease_expires_at < now,
            ),
        )
        .values(
            status=KnowledgeCategoryRevisionStatus.FAILED,
            failure_code=PROCESSING_LEASE_EXPIRED_CODE,
            error_message=PROCESSING_LEASE_EXPIRED_MESSAGE,
            processing_token=None,
            processing_started_at=None,
            lease_expires_at=None,
        )
    )
    await db.commit()
    return int(result.rowcount or 0)
