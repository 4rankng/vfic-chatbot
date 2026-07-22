"""Pure ingestion lifecycle policy."""

from __future__ import annotations

from enum import StrEnum


class IngestionState(StrEnum):
    RECEIVED = "RECEIVED"
    STORED = "STORED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    CLASSIFIED = "CLASSIFIED"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    INDEXED = "INDEXED"
    FAILED_TRANSIENT = "FAILED_TRANSIENT"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"


ALLOWED_STATE_TRANSITIONS: dict[IngestionState, frozenset[IngestionState]] = {
    IngestionState.RECEIVED: frozenset(
        {
            IngestionState.STORED,
            IngestionState.FAILED_TRANSIENT,
            IngestionState.FAILED_PERMANENT,
            IngestionState.QUARANTINED,
            IngestionState.SUPERSEDED,
        }
    ),
    IngestionState.STORED: frozenset(
        {
            IngestionState.PARSED,
            IngestionState.FAILED_TRANSIENT,
            IngestionState.FAILED_PERMANENT,
            IngestionState.SUPERSEDED,
        }
    ),
    IngestionState.PARSED: frozenset(
        {
            IngestionState.NORMALIZED,
            IngestionState.FAILED_TRANSIENT,
            IngestionState.FAILED_PERMANENT,
            IngestionState.SUPERSEDED,
        }
    ),
    IngestionState.NORMALIZED: frozenset(
        {
            IngestionState.CLASSIFIED,
            IngestionState.FAILED_TRANSIENT,
            IngestionState.FAILED_PERMANENT,
        }
    ),
    IngestionState.CLASSIFIED: frozenset(
        {
            IngestionState.EXTRACTED,
            IngestionState.FAILED_TRANSIENT,
            IngestionState.FAILED_PERMANENT,
        }
    ),
    IngestionState.EXTRACTED: frozenset(
        {
            IngestionState.VALIDATED,
            IngestionState.REVIEW_REQUIRED,
            IngestionState.FAILED_TRANSIENT,
            IngestionState.FAILED_PERMANENT,
        }
    ),
    IngestionState.VALIDATED: frozenset(
        {
            IngestionState.REVIEW_REQUIRED,
            IngestionState.APPROVED,
            IngestionState.FAILED_PERMANENT,
        }
    ),
    IngestionState.REVIEW_REQUIRED: frozenset(
        {
            IngestionState.APPROVED,
            IngestionState.FAILED_PERMANENT,
            IngestionState.QUARANTINED,
        }
    ),
    IngestionState.APPROVED: frozenset({IngestionState.PUBLISHED}),
    IngestionState.PUBLISHED: frozenset({IngestionState.INDEXED}),
    IngestionState.INDEXED: frozenset(),
    IngestionState.FAILED_TRANSIENT: frozenset({IngestionState.RECEIVED}),
    IngestionState.FAILED_PERMANENT: frozenset(),
    IngestionState.QUARANTINED: frozenset(),
    IngestionState.SUPERSEDED: frozenset({IngestionState.RECEIVED}),
}

TERMINAL_INGESTION_STATES = frozenset(
    {
        IngestionState.INDEXED,
        IngestionState.FAILED_PERMANENT,
        IngestionState.QUARANTINED,
    }
)


class IllegalIngestionTransition(ValueError):
    """Raised when an ingestion state transition violates the lifecycle."""


def ensure_ingestion_transition(
    current: IngestionState | str,
    target: IngestionState | str,
    *,
    reason: str | None = None,
) -> bool:
    """Validate a transition; return ``False`` for an idempotent no-op."""
    current_state = IngestionState(current)
    target_state = IngestionState(target)
    if current_state is target_state:
        return False
    if target_state not in ALLOWED_STATE_TRANSITIONS[current_state]:
        suffix = f" ({reason})" if reason else ""
        raise IllegalIngestionTransition(
            f"illegal transition {current_state.value} → {target_state.value}{suffix}"
        )
    return True


__all__ = [
    "ALLOWED_STATE_TRANSITIONS",
    "TERMINAL_INGESTION_STATES",
    "IllegalIngestionTransition",
    "IngestionState",
    "ensure_ingestion_transition",
]

