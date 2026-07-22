"""Framework-free project and knowledge domain policies."""

from app.project_knowledge.domain.ingestion import (
    ALLOWED_STATE_TRANSITIONS,
    TERMINAL_INGESTION_STATES,
    IllegalIngestionTransition,
    IngestionState,
    ensure_ingestion_transition,
)
from app.project_knowledge.domain.project import (
    ProjectActivationFacts,
    project_activation_error,
)

__all__ = [
    "ALLOWED_STATE_TRANSITIONS",
    "TERMINAL_INGESTION_STATES",
    "IllegalIngestionTransition",
    "IngestionState",
    "ProjectActivationFacts",
    "ensure_ingestion_transition",
    "project_activation_error",
]
