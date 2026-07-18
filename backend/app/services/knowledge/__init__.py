"""Knowledge training-pipeline package (digest -> embed -> index -> features).

Public API re-exported here; importers should depend on ``app.services.knowledge`` rather
than the internal submodules.

Layering inside this package:
    prompts/      string constants (no imports)
    extraction/   digest section chunker (app.core only)
    coercion/     pure LLM-output validation (imports prompts)
    repository/   raw-SQL data access (app.core + sqlalchemy only)
    pipeline/     orchestrator (imports the four above)
    service/      high-level CRUD + ingest orchestration
    file_extraction/  DOCX/text extraction utilities
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
from app.services.knowledge.extraction import DigestSections, split_for_digest
from app.services.knowledge.file_extraction import (
    KnowledgeFileExtractionError,
    extract_text,
)
from app.services.knowledge.pipeline import (
    Embedder,
    KnowledgePipeline,
    LLMJson,
    sync_project_highlights,
)
from app.services.knowledge.service import KnowledgeService

__all__ = [
    "DigestError",
    "Embedder",
    "KnowledgeFileExtractionError",
    "KnowledgePipeline",
    "KnowledgeService",
    "LLMJson",
    "CANONICAL_SCHEMA_VERSIONS",
    "CanonicalValidationError",
    "DigestSections",
    "SCHEMA_VERSION",
    "extract_text",
    "load_template",
    "parse_canonical_markdown",
    "split_for_digest",
    "sync_project_highlights",
    "validate_digest",
]
