"""Pure mapping helpers — row → schema. No DB, no I/O, no side effects."""

from __future__ import annotations

from typing import Any

from app.schemas.projects import FeatureOut


def _feature_from_row(r: Any) -> FeatureOut:
    return FeatureOut(
        id=r.id,
        project_id=r.project_id,
        feature_id=r.feature_id,
        feature_key=r.feature_key,
        name_vi=r.name_vi,
        category=r.category,
        worker_question_vi=r.worker_question_vi,
        value_text=r.value_text,
        value_json=r.value_json or {},
        strength_score=float(r.strength_score),
        display_priority=r.display_priority,
        is_highlight=r.is_highlight,
        is_missing=r.is_missing,
        needs_clarification=r.needs_clarification,
        evidence_text=r.evidence_text,
        source_document_id=r.source_document_id,
        updated_at=r.updated_at,
    )


def _faq_answer_from_content(content: str | None, question: str) -> str:
    text_value = (content or "").strip()
    prefix = f"FAQ: {question}".strip()
    if prefix and text_value.startswith(prefix):
        text_value = text_value[len(prefix) :].strip()
    return text_value or (content or "")
