"""Compatible public exports without loading the entire ingestion graph.

Importing a leaf helper must not construct its package's persistence and provider
dependencies. Public exports load their owning module on first access; concrete
service callers retain the same classes, functions and names.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.knowledge.canonical import (
        CANONICAL_SCHEMA_VERSIONS as CANONICAL_SCHEMA_VERSIONS,
        CanonicalValidationError as CanonicalValidationError,
        SCHEMA_VERSION as SCHEMA_VERSION,
        load_template as load_template,
        parse_canonical_markdown as parse_canonical_markdown,
    )
    from app.services.knowledge.coercion import (
        DigestError as DigestError,
        validate_digest as validate_digest,
    )
    from app.services.knowledge.extraction import (
        DigestSections as DigestSections,
        split_for_digest as split_for_digest,
    )
    from app.services.knowledge.file_extraction import (
        KnowledgeFileExtractionError as KnowledgeFileExtractionError,
        extract_text as extract_text,
    )
    from app.services.knowledge.pipeline import (
        Embedder as Embedder,
        KnowledgePipeline as KnowledgePipeline,
        LLMJson as LLMJson,
        sync_project_highlights as sync_project_highlights,
    )
    from app.services.knowledge.service import KnowledgeService as KnowledgeService

_EXPORT_MODULES = {
    "DigestError": "coercion",
    "Embedder": "pipeline",
    "KnowledgeFileExtractionError": "file_extraction",
    "KnowledgePipeline": "pipeline",
    "KnowledgeService": "service",
    "LLMJson": "pipeline",
    "CANONICAL_SCHEMA_VERSIONS": "canonical",
    "CanonicalValidationError": "canonical",
    "DigestSections": "extraction",
    "SCHEMA_VERSION": "canonical",
    "extract_text": "file_extraction",
    "load_template": "canonical",
    "parse_canonical_markdown": "canonical",
    "split_for_digest": "extraction",
    "sync_project_highlights": "pipeline",
    "validate_digest": "coercion",
}

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


def __getattr__(name: str) -> Any:
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
