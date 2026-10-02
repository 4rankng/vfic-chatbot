"""Deterministic validation helpers for project-owned RAG category documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.knowledge_categories import (
    CATEGORY_DOCUMENT_MODELS,
    MAX_CATEGORY_RECORDS,
    CategoryDocument,
)
from app.project_knowledge.domain.category import (
    KnowledgeCategoryKey,
    category_payload_checksum,
    category_record_limit_exceeded,
    category_replacement_is_empty,
)
from app.project_knowledge.domain.category_catalog import (
    CATEGORY_DEFINITIONS as CATEGORY_DEFINITIONS,
    CategoryDefinition as CategoryDefinition,
    get_category_definition as get_category_definition,
)
from app.project_knowledge.domain.legacy_job_references import strip_legacy_job_reference_fields
from app.services.knowledge.text_ingestion import normalize_kb_value


_TEMPLATE_DIR = Path(__file__).with_name("templates") / "categories"


class EmptyCategoryError(ValueError):
    """Raised when replacement content has no rows and clear was not requested."""


class CategoryMarkdownError(ValueError):
    """Raised when category content is not one well-formed Category Markdown v1 document."""


def load_category_template(key: KnowledgeCategoryKey | str) -> str:
    definition = get_category_definition(key)
    return (_TEMPLATE_DIR / definition.template_filename).read_text(encoding="utf-8")


_FULL_TEMPLATE_FILENAME = "mau-kb-du-an.md"


def build_project_knowledge_template() -> str:
    """Render ONE operator-facing project brief with fill-in placeholders.

    The template is the BRIEF shape the reference files use (samsung-sds.md):
    a "Thông tin tổng quan" bullet block plus one ``## <label>`` section per
    category with its bullet fields. That is exactly the document the brief
    parser reads, so a fill-and-upload file round-trips with no conversion.
    The record-shape per-category templates stay the internal edit lane.
    """
    return (_TEMPLATE_DIR.parent / _FULL_TEMPLATE_FILENAME).read_text(
        encoding="utf-8"
    )


def validate_category_payload(
    key: KnowledgeCategoryKey | str,
    payload: dict[str, Any],
    *,
    allow_empty: bool = False,
) -> CategoryDocument:
    category_key = KnowledgeCategoryKey(key)
    definition = get_category_definition(category_key)
    records = payload.get(definition.list_field)
    if isinstance(records, list) and category_record_limit_exceeded(
        len(records), MAX_CATEGORY_RECORDS
    ):
        raise CategoryMarkdownError(
            f"category exceeds the {MAX_CATEGORY_RECORDS:,} record limit"
        )
    normalized_payload = normalize_kb_value(strip_legacy_job_reference_fields(payload))
    document = CATEGORY_DOCUMENT_MODELS[category_key].model_validate(normalized_payload)
    if not allow_empty and category_replacement_is_empty(
        len(getattr(document, definition.list_field))
    ):
        raise EmptyCategoryError(
            "category replacement must contain at least one row; use the explicit clear action"
        )
    return document


def canonical_category_json(document: CategoryDocument) -> str:
    payload = document.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def category_checksum(document: CategoryDocument) -> str:
    return category_payload_checksum(document.model_dump(mode="json"))
