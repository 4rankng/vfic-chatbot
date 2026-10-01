"""Category lookup has one pure owner independent of database projections."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from app.project_knowledge.domain.category import KnowledgeCategoryKey
from app.project_knowledge.domain.category_catalog import (
    CATEGORY_DEFINITIONS,
    get_category_definition,
)


def test_category_registry_covers_every_schema_once_in_canonical_order():
    from app.schemas.knowledge_categories import (
        CATEGORY_DOCUMENT_MODELS,
        KnowledgeCategoryKey as SchemaCategoryKey,
    )

    keys = [definition.key for definition in CATEGORY_DEFINITIONS]
    assert keys == list(KnowledgeCategoryKey)
    assert set(keys) == set(CATEGORY_DOCUMENT_MODELS)
    assert SchemaCategoryKey is KnowledgeCategoryKey

    for definition in CATEGORY_DEFINITIONS:
        model = CATEGORY_DOCUMENT_MODELS[definition.key]
        assert model.model_fields["category"].default is definition.key
        assert definition.list_field in model.model_fields
        assert definition.template_filename == f"{definition.list_field}.md"
        assert get_category_definition(definition.key.value) is definition


def test_category_lookup_rejects_unknown_identity():
    with pytest.raises(ValueError):
        get_category_definition("unknown")


def test_public_knowledge_exports_keep_identity_and_discovery():
    import app.services.knowledge as knowledge
    from importlib import import_module

    expected = {
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
    assert knowledge.__all__ == list(expected)
    assert set(expected).issubset(dir(knowledge))
    for name, module in expected.items():
        assert getattr(knowledge, name) is getattr(
            import_module(f"app.services.knowledge.{module}"), name
        )
    with pytest.raises(AttributeError):
        getattr(knowledge, "unknown_export")


def test_retrieval_category_lookup_does_not_load_projection_or_database_adapters():
    code = textwrap.dedent("""\
        from types import SimpleNamespace
        import sys
        from app.services.knowledge.retrieval_selftest import _record_list_field

        assert _record_list_field(SimpleNamespace(category="jobs")) == "jobs"
        assert _record_list_field(SimpleNamespace(category="unknown")) is None
        assert _record_list_field(SimpleNamespace()) is None
        unwanted = [name for name in sys.modules if name.startswith((
            "sqlalchemy", "pydantic", "app.models",
            "app.services.knowledge.category_projections",
        ))]
        assert unwanted == [], unwanted
    """)
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
