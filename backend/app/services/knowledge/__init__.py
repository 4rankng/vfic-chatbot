"""Knowledge training-pipeline package (digest -> embed -> index -> features).

Public API re-exported here; importers should depend on ``app.services.knowledge`` rather
than the internal submodules.

Layering inside this package:
    prompts/      string constants (no imports)
    extraction/   digest section chunker (app.core only)
    coercion/     pure LLM-output validation (imports prompts)
    repository/   raw-SQL data access (app.core + sqlalchemy only)
    pipeline/     orchestrator (imports the four above)
"""
from __future__ import annotations

from app.services.knowledge.coercion import DigestError, validate_digest
from app.services.knowledge.canonical import (
    CANONICAL_SCHEMA_VERSIONS,
    CanonicalValidationError,
    SCHEMA_VERSION,
    load_template,
    parse_canonical_markdown,
)
from app.services.knowledge.extraction import split_for_digest
from app.services.knowledge.pipeline import (
    Embedder,
    KnowledgePipeline,
    LLMJson,
    sync_project_highlights,
)

__all__ = [
    "DigestError",
    "Embedder",
    "KnowledgePipeline",
    "LLMJson",
    "CANONICAL_SCHEMA_VERSIONS",
    "CanonicalValidationError",
    "SCHEMA_VERSION",
    "load_template",
    "parse_canonical_markdown",
    "split_for_digest",
    "sync_project_highlights",
    "validate_digest",
]
