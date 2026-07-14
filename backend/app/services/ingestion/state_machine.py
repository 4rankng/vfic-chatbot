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

logger = logging.getLogger(__name__)


class IllegalTransition(ValueError):
    """Raised when a state transition is not in ALLOWED_TRANSITIONS."""


# Directive §8 transition table.
ALLOWED_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.RECEIVED: {
        DocumentStatus.STORED,
        DocumentStatus.FAILED_TRANSIENT,
        DocumentStatus.FAILED_PERMANENT,
        DocumentStatus.QUARANTINED,
        DocumentStatus.SUPERSEDED,
    },
    DocumentStatus.STORED: {
        DocumentStatus.PARSED,
        DocumentStatus.FAILED_TRANSIENT,
        DocumentStatus.FAILED_PERMANENT,
        DocumentStatus.SUPERSEDED,
    },
    DocumentStatus.PARSED: {
        DocumentStatus.NORMALIZED,
        DocumentStatus.FAILED_TRANSIENT,
        DocumentStatus.FAILED_PERMANENT,
        DocumentStatus.SUPERSEDED,
    },
    DocumentStatus.NORMALIZED: {
        DocumentStatus.CLASSIFIED,
        DocumentStatus.FAILED_TRANSIENT,
        DocumentStatus.FAILED_PERMANENT,
    },
    DocumentStatus.CLASSIFIED: {
        DocumentStatus.EXTRACTED,
        DocumentStatus.FAILED_TRANSIENT,
        DocumentStatus.FAILED_PERMANENT,
    },
    DocumentStatus.EXTRACTED: {
        DocumentStatus.VALIDATED,
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.FAILED_TRANSIENT,
        DocumentStatus.FAILED_PERMANENT,
    },
    DocumentStatus.VALIDATED: {
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.APPROVED,
        DocumentStatus.FAILED_PERMANENT,
    },
    DocumentStatus.REVIEW_REQUIRED: {
        DocumentStatus.APPROVED,
        DocumentStatus.FAILED_PERMANENT,
        DocumentStatus.QUARANTINED,
    },
    DocumentStatus.APPROVED: {DocumentStatus.PUBLISHED},
    DocumentStatus.PUBLISHED: {DocumentStatus.INDEXED},
    DocumentStatus.INDEXED: set(),  # terminal
    DocumentStatus.FAILED_TRANSIENT: {DocumentStatus.RECEIVED},  # retry from start
    DocumentStatus.FAILED_PERMANENT: set(),  # terminal
    DocumentStatus.QUARANTINED: set(),  # terminal (admin review)
    DocumentStatus.SUPERSEDED: {DocumentStatus.RECEIVED},  # re-ingest as new version
}

TERMINAL_STATES = {
    DocumentStatus.INDEXED,
    DocumentStatus.FAILED_PERMANENT,
    DocumentStatus.QUARANTINED,
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
    if current == new_status:
        return doc  # idempotent
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise IllegalTransition(
            f"illegal transition {current.value} → {new_status.value}"
            + (f" ({reason})" if reason else "")
        )
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
