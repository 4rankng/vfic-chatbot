"""Deterministic validation helpers for project-owned RAG category documents.

The job-reference rule has two halves that belong together: the pure check
(:func:`validate_job_references`) and the project-scoped lookup of which job ids
the *sibling* active revisions currently publish (:func:`validate_active_job_references`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeCategory, KnowledgeCategoryRevision
from app.schemas.knowledge_categories import (
    CATEGORY_DOCUMENT_MODELS,
    MAX_CATEGORY_RECORDS,
    CategoryDocument,
    KnowledgeCategoryKey,
)
from app.project_knowledge.domain.category import (
    category_payload_checksum,
    category_record_limit_exceeded,
    category_replacement_is_empty,
    unknown_job_references,
)
from app.services.knowledge.text_ingestion import normalize_kb_value


_TEMPLATE_DIR = Path(__file__).with_name("templates") / "categories"


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    key: KnowledgeCategoryKey
    label_vi: str
    list_field: str
    template_filename: str


CATEGORY_DEFINITIONS: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        KnowledgeCategoryKey.JOBS,
        "Vị trí tuyển dụng",
        "jobs",
        "jobs.md",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.COMPENSATION,
        "Lương & thu nhập",
        "compensation",
        "compensation.md",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.REQUIREMENTS,
        "Yêu cầu ứng viên",
        "requirements",
        "requirements.md",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.WORK_SCHEDULES,
        "Ca làm việc",
        "work_schedules",
        "work_schedules.md",
    ),
    CategoryDefinition(KnowledgeCategoryKey.BENEFITS, "Phúc lợi", "benefits", "benefits.md"),
    CategoryDefinition(
        KnowledgeCategoryKey.ACCOMMODATION,
        "Chỗ ở",
        "accommodation",
        "accommodation.md",
    ),
    CategoryDefinition(KnowledgeCategoryKey.MEALS, "Bữa ăn", "meals", "meals.md"),
    CategoryDefinition(
        KnowledgeCategoryKey.TRANSPORTATION,
        "Đưa đón & lịch xe",
        "transportation",
        "transportation.md",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.INSURANCE,
        "Bảo hiểm",
        "insurance",
        "insurance.md",
    ),
    CategoryDefinition(
        KnowledgeCategoryKey.APPLICATION,
        "Ứng tuyển & nhận việc",
        "application",
        "application.md",
    ),
    CategoryDefinition(KnowledgeCategoryKey.CONTACTS, "Liên hệ", "contacts", "contacts.md"),
    CategoryDefinition(
        KnowledgeCategoryKey.FAQ,
        "Câu hỏi thường gặp",
        "faq",
        "faq.md",
    ),
)

_DEFINITIONS_BY_KEY = {definition.key: definition for definition in CATEGORY_DEFINITIONS}


class EmptyCategoryError(ValueError):
    """Raised when replacement content has no rows and clear was not requested."""


class UnknownJobReferenceError(ValueError):
    """Raised when a category references a job absent from the current Jobs category."""


class CategoryMarkdownError(ValueError):
    """Raised when category content is not one well-formed Category Markdown v1 document."""


def get_category_definition(key: KnowledgeCategoryKey | str) -> CategoryDefinition:
    return _DEFINITIONS_BY_KEY[KnowledgeCategoryKey(key)]


def load_category_template(key: KnowledgeCategoryKey | str) -> str:
    definition = get_category_definition(key)
    return (_TEMPLATE_DIR / definition.template_filename).read_text(encoding="utf-8")


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
    normalized_payload = normalize_kb_value(payload)
    document = CATEGORY_DOCUMENT_MODELS[category_key].model_validate(normalized_payload)
    if not allow_empty and category_replacement_is_empty(
        len(getattr(document, definition.list_field))
    ):
        raise EmptyCategoryError(
            "category replacement must contain at least one row; use the explicit clear action"
        )
    return document


def validate_job_references(
    document: CategoryDocument,
    known_job_ids: set[str],
) -> None:
    definition = get_category_definition(document.category)
    if definition.key is KnowledgeCategoryKey.JOBS:
        return

    unknown = unknown_job_references(
        (getattr(record, "job_ids", []) for record in getattr(document, definition.list_field)),
        known_job_ids,
    )
    if unknown:
        raise UnknownJobReferenceError(
            f"unknown job reference(s) in this project: {', '.join(sorted(unknown))}"
        )


async def validate_active_job_references(
    db: AsyncSession,
    project_id: uuid.UUID,
    document: CategoryDocument,
) -> None:
    """Check ``document``'s job references against the project's *active* content.

    The JOBS category is checked in the other direction: every other category's
    active revision must still resolve against the job ids this document
    publishes. Anything else is checked against the active JOBS revision.
    """
    if document.category is KnowledgeCategoryKey.JOBS:
        new_job_ids = {item.id for item in document.jobs}
        sibling_categories = (
            await db.scalars(
                select(KnowledgeCategory).where(
                    KnowledgeCategory.project_id == project_id,
                    KnowledgeCategory.category_key != KnowledgeCategoryKey.JOBS.value,
                    KnowledgeCategory.active_revision_id.is_not(None),
                )
            )
        ).all()
        for sibling in sibling_categories:
            revision = await db.get(
                KnowledgeCategoryRevision,
                sibling.active_revision_id,
            )
            if revision is None:
                continue
            sibling_document = validate_category_payload(
                sibling.category_key,
                revision.normalized_payload,
            )
            validate_job_references(sibling_document, new_job_ids)
        return
    jobs_category = await db.scalar(
        select(KnowledgeCategory).where(
            KnowledgeCategory.project_id == project_id,
            KnowledgeCategory.category_key == KnowledgeCategoryKey.JOBS.value,
        )
    )
    known_ids: set[str] = set()
    if jobs_category and jobs_category.active_revision_id:
        revision = await db.get(
            KnowledgeCategoryRevision,
            jobs_category.active_revision_id,
        )
        if revision:
            known_ids = {
                str(item["id"])
                for item in revision.normalized_payload.get("jobs", [])
                if isinstance(item, dict) and item.get("id")
            }
    validate_job_references(document, known_ids)


def canonical_category_json(document: CategoryDocument) -> str:
    payload = document.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def category_checksum(document: CategoryDocument) -> str:
    return category_payload_checksum(document.model_dump(mode="json"))
