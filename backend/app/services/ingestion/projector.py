"""Search projection generator (Tech-Lead Directive §9 stage 10 + §7).

Generates disposable search documents from authoritative rows. Projections are
derived, never the source of truth — they can be regenerated from the
authoritative tables anytime. Each projection has: entity_id, entity_type,
scope, section_type, language, rendered_text, structured_payload.

Batch embedding is the caller's responsibility (P2-7 step 2); this module
produces the texts to embed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Projection:
    """One disposable search document derived from an authoritative row."""

    entity_id: str
    entity_type: str
    scope_type: str
    section_type: str
    language: str
    rendered_text: str
    structured_payload: dict


def project_benefit(row: Any) -> Projection:
    """Render a JobBenefit row to a Vietnamese search document."""
    text_parts = [row.name]
    if row.value is not None and row.currency:
        text_parts.append(f"{int(row.value):,} {row.currency}/{row.cadence or 'tháng'}")
    if row.eligibility:
        text_parts.append(f"điều kiện: {row.eligibility}")
    return Projection(
        entity_id=str(getattr(row, "id", "")),
        entity_type="benefit",
        scope_type=row.scope_type,
        section_type="benefit",
        language="vi",
        rendered_text=". ".join(text_parts),
        structured_payload={
            "name": row.name,
            "value": row.value,
            "currency": row.currency,
            "cadence": row.cadence,
        },
    )


def project_working_hours(row: Any) -> Projection:
    days = ", ".join(row.days or [])
    text = f"Giờ làm việc: {row.start_time} - {row.end_time} ({days})"
    if row.crosses_midnight:
        text += " (ca qua đêm)"
    return Projection(
        entity_id=str(getattr(row, "id", "")),
        entity_type="working_hours",
        scope_type=row.scope_type,
        section_type="working_hours",
        language="vi",
        rendered_text=text,
        structured_payload={
            "start_time": str(row.start_time) if row.start_time else None,
            "end_time": str(row.end_time) if row.end_time else None,
            "days": row.days,
        },
    )


def project_job_requirement(row: Any) -> Projection:
    return Projection(
        entity_id=str(getattr(row, "id", "")),
        entity_type="job_requirement",
        scope_type="job_posting",
        section_type="job_requirements",
        language="vi",
        rendered_text=row.requirement_text,
        structured_payload={
            "category": row.category,
            "is_required": row.is_required,
        },
    )


def project_faq(row: Any) -> Projection:
    return Projection(
        entity_id=str(getattr(row, "id", "")),
        entity_type="faq",
        scope_type=row.scope_type,
        section_type="faq",
        language=row.language or "vi",
        rendered_text=f"{row.canonical_question}\n{row.answer}",
        structured_payload={
            "question": row.canonical_question,
            "answer": row.answer,
            "resolution_type": row.resolution_type,
        },
    )


_PROJECTORS = {
    "benefit": project_benefit,
    "working_hours": project_working_hours,
    "job_requirement": project_job_requirement,
    "faq": project_faq,
}


def project_row(row: Any) -> Projection | None:
    """Dispatch to the right projector by entity_type attribute.

    Returns None when no projector applies (caller skips indexing for that row).
    """
    et = getattr(row, "entity_type", None)
    # Authoritative-table rows don't carry entity_type; infer from table name.
    if et is None:
        tbl = getattr(row, "__tablename__", None) or type(row).__name__.lower()
        if "benefit" in tbl:
            et = "benefit"
        elif "working_hours" in tbl:
            et = "working_hours"
        elif "requirement" in tbl:
            et = "job_requirement"
        elif "faq" in tbl:
            et = "faq"
    fn = _PROJECTORS.get(et)
    if fn is None:
        return None
    return fn(row)


def projections_for_batch(rows: list) -> list[Projection]:
    """Project many rows. Skips rows with no matching projector."""
    out: list[Projection] = []
    for r in rows:
        p = project_row(r)
        if p is not None:
            out.append(p)
    return out
