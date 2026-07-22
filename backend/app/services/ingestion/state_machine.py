"""Ingestion state machine (Tech-Lead Directive §8).

The directive requires ingestion to be an explicit, idempotent state machine:
RECEIVED → STORED → PARSED → NORMALIZED → CLASSIFIED → EXTRACTED → VALIDATED
→ REVIEW_REQUIRED|APPROVED → PUBLISHED → INDEXED, with failure states
FAILED_TRANSIENT, FAILED_PERMANENT, QUARANTINED, SUPERSEDED.

This module ships the state machine primitive + the resumable orchestrator
spine. Stage implementations (parse, normalize, classify, extract, validate,
review, index) ship in P2-2..P2-7; here they are stubs that transition the doc
forward so the spine is testable today.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provenance import DocumentStatus, SourceDocument
from app.project_knowledge.domain.ingestion import (
    ALLOWED_STATE_TRANSITIONS,
    TERMINAL_INGESTION_STATES,
    IllegalIngestionTransition,
    IngestionState,
    ensure_ingestion_transition,
)

logger = logging.getLogger(__name__)


IllegalTransition = IllegalIngestionTransition


# Directive §8 transition table.
ALLOWED_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus(current.value): {
        DocumentStatus(target.value) for target in targets
    }
    for current, targets in ALLOWED_STATE_TRANSITIONS.items()
}

TERMINAL_STATES = {
    DocumentStatus(state.value) for state in TERMINAL_INGESTION_STATES
}


async def transition(
    db: AsyncSession,
    doc: SourceDocument,
    new_status: DocumentStatus,
    *,
    reason: str | None = None,
) -> SourceDocument:
    """Assert ``new_status`` is legal from ``doc.status``, then update + commit.

    Idempotent: transitioning to the current state is a no-op. Raises
    IllegalTransition on disallowed transitions.
    """
    current = DocumentStatus(doc.status)
    if not ensure_ingestion_transition(
        IngestionState(current.value),
        IngestionState(new_status.value),
        reason=reason,
    ):
        return doc  # idempotent
    doc.status = new_status.value
    await db.commit()
    await db.refresh(doc)
    logger.info(
        "ingestion transition doc=%s %s → %s%s",
        doc.id,
        current.value,
        new_status.value,
        f" reason={reason}" if reason else "",
    )
    return doc


async def load_doc(db: AsyncSession, doc_id: int) -> SourceDocument | None:
    return await db.get(SourceDocument, doc_id)
