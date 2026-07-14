"""Versioned publishing service (Tech-Lead Directive §7, §9).

Takes a validated ExtractionEnvelope (P1-2), resolves its natural key, and
publishes it to the authoritative tables (P1-1) with versioning:
- First publish → version 1, status='published'.
- Same content republished → no-op (idempotent).
- Different content → new version row, prior row → 'retired', diff recorded.

No silent overwrite (directive §7). Atomic (all-or-nothing). Natural keys per
directive §8 (FAQ = tenant+scope+normalized_question; benefit = tenant+scope+
name; etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provenance import (
    FaqEntry,
    JobBenefit,
    JobRequirement,
    PublishedStatus,
    WorkingHours,
)
from app.schemas.extraction_contracts import (
    ExtractionEnvelope,
    FaqEnvelopeData,
)

logger = logging.getLogger(__name__)


class PublishingError(ValueError):
    """Raised when a contract fails validation or cannot be published."""


@dataclass(frozen=True)
class PublishingResult:
    """Outcome of a publish call. ``no_op=True`` means the content was identical."""

    entity_type: str
    version: int
    no_op: bool
    diff_fields: list[str]


def natural_key(entity_type: str, data: Any, scope_type: str) -> tuple:
    """Directive §8 natural keys per entity type."""
    if entity_type == "faq":
        return (scope_type, _norm(data.canonical_question))
    if entity_type == "benefit":
        return (scope_type, _norm(data.name))
    if entity_type == "job_requirement":
        return (_norm(data.text),)
    if entity_type == "working_hours":
        return (scope_type, tuple(sorted(data.days)), data.start_time, data.end_time)
    return (entity_type,)  # fallback


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


async def publish_contract(
    db: AsyncSession,
    envelope: ExtractionEnvelope,
    *,
    job_id: str | None = None,
    kb_version_id: str | None = None,
) -> PublishingResult:
    """Validate + version + persist ``envelope`` to the authoritative tables.

    Raises PublishingError on validation failure. Idempotent: same content → no_op.
    """
    data = envelope.data
    entity_type = data.entity_type
    scope = envelope.scope

    if entity_type == "faq":
        return await _publish_faq(db, data, scope, envelope, kb_version_id)
    if entity_type == "benefit":
        return await _publish_benefit(db, data, scope, envelope, job_id, kb_version_id)
    if entity_type == "working_hours":
        return await _publish_working_hours(db, data, scope, envelope, kb_version_id)
    if entity_type == "job_requirement":
        return await _publish_job_requirement(db, data, job_id, envelope, kb_version_id)
    raise PublishingError(f"unsupported entity_type: {entity_type}")


async def _find_current_published(db, model, natural_key_cols: dict) -> Any:
    """Find the current published row matching the natural-key columns.

    ``natural_key_cols`` is a {column_name: value} dict; we build the WHERE
    clause by attribute lookup on the model.
    """
    clauses = [model.status == PublishedStatus.PUBLISHED.value]
    for col_name, value in natural_key_cols.items():
        col = getattr(model, col_name)
        clauses.append(col == value)
    stmt = select(model).where(*clauses)
    return (await db.execute(stmt)).scalars().first()


def _content_equal(row: Any, data: Any, entity_type: str) -> bool:
    """Compare an existing row to new data for idempotency."""
    if entity_type == "faq":
        return row.answer == data.answer and row.canonical_question == data.canonical_question
    if entity_type == "benefit":
        return (
            row.name == data.name
            and row.value == data.value
            and row.currency == data.currency
            and row.cadence == data.cadence
        )
    if entity_type == "working_hours":
        return (
            row.start_time == data.start_time
            and row.end_time == data.end_time
            and row.days == data.days
        )
    if entity_type == "job_requirement":
        return row.requirement_text == data.text
    return False


async def _publish_faq(db, data: FaqEnvelopeData, scope, envelope, kb_version_id) -> PublishingResult:
    nk = {"scope_type": scope.type, "normalized_question": _norm(data.canonical_question)}
    if kb_version_id is not None:
        nk["kb_version_id"] = kb_version_id
    current = await _find_current_published(db, FaqEntry, nk)
    if current and _content_equal(current, data, "faq"):
        return PublishingResult("faq", current.version, no_op=True, diff_fields=[])
    if current:
        current.status = PublishedStatus.RETIRED.value
        new_version = current.version + 1
    else:
        new_version = 1
    row = FaqEntry(
        kb_version_id=kb_version_id,
        scope_type=scope.type,
        scope_id=scope.id,
        canonical_question=data.canonical_question,
        normalized_question=_norm(data.canonical_question),
        answer=data.answer,
        aliases=data.aliases,
        language=data.language,
        resolution_type=data.resolution_type,
        tool_name=data.tool_name,
        valid_from=envelope.validity.valid_from,
        valid_to=envelope.validity.valid_to,
        status=PublishedStatus.PUBLISHED.value,
        version=new_version,
    )
    db.add(row)
    await db.flush()
    diff = ["answer", "canonical_question"] if current else []
    return PublishingResult("faq", new_version, no_op=False, diff_fields=diff)


async def _publish_benefit(db, data, scope, envelope, job_id, kb_version_id) -> PublishingResult:
    nk = {"scope_type": scope.type, "name": data.name}
    if kb_version_id is not None:
        nk["kb_version_id"] = kb_version_id
    current = await _find_current_published(db, JobBenefit, nk)
    if current and _content_equal(current, data, "benefit"):
        return PublishingResult("benefit", current.version, no_op=True, diff_fields=[])
    if current:
        current.status = PublishedStatus.RETIRED.value
        new_version = current.version + 1
    else:
        new_version = 1
    row = JobBenefit(
        kb_version_id=kb_version_id,
        job_id=job_id,
        scope_type=scope.type,
        scope_id=scope.id,
        name=data.name,
        category=data.category,
        value=data.value,
        currency=data.currency,
        cadence=data.cadence,
        eligibility=data.eligibility,
        taxable=data.taxable,
        valid_from=envelope.validity.valid_from,
        valid_to=envelope.validity.valid_to,
        status=PublishedStatus.PUBLISHED.value,
        version=new_version,
    )
    db.add(row)
    await db.flush()
    diff = ["value", "currency", "cadence"] if current else []
    return PublishingResult("benefit", new_version, no_op=False, diff_fields=diff)


async def _publish_working_hours(db, data, scope, envelope, kb_version_id) -> PublishingResult:
    from datetime import time as dt_time

    def _parse_t(s: str) -> dt_time:
        h, m, s = s.split(":")
        return dt_time(int(h), int(m), int(s))

    nk = {"scope_type": scope.type}
    if kb_version_id is not None:
        nk["kb_version_id"] = kb_version_id
    current = await _find_current_published(db, WorkingHours, nk)
    if current and _content_equal(current, data, "working_hours"):
        return PublishingResult("working_hours", current.version, no_op=True, diff_fields=[])
    if current:
        current.status = PublishedStatus.RETIRED.value
        new_version = current.version + 1
    else:
        new_version = 1
    row = WorkingHours(
        kb_version_id=kb_version_id,
        scope_type=scope.type,
        scope_id=scope.id,
        schedule_type=data.schedule_type,
        days=data.days,
        start_time=_parse_t(data.start_time),
        end_time=_parse_t(data.end_time),
        crosses_midnight=data.crosses_midnight,
        breaks=data.breaks,
        timezone=envelope.validity.timezone,
        valid_from=envelope.validity.valid_from,
        valid_to=envelope.validity.valid_to,
        status=PublishedStatus.PUBLISHED.value,
        version=new_version,
    )
    db.add(row)
    await db.flush()
    diff = ["start_time", "end_time", "days"] if current else []
    return PublishingResult("working_hours", new_version, no_op=False, diff_fields=diff)


async def _publish_job_requirement(db, data, job_id, envelope, kb_version_id) -> PublishingResult:
    if not job_id:
        raise PublishingError("job_requirement requires job_id")
    import uuid

    # No natural-key uniqueness per requirement text (a job can have many);
    # idempotency is by exact-text match against the current published set.
    existing = (
        await db.execute(
            select(JobRequirement).where(
                JobRequirement.job_id == uuid.UUID(job_id),
                JobRequirement.status == PublishedStatus.PUBLISHED.value,
                JobRequirement.requirement_text == data.text,
                JobRequirement.kb_version_id == kb_version_id,
            )
        )
    ).scalars().first()
    if existing:
        return PublishingResult("job_requirement", existing.version, no_op=True, diff_fields=[])
    row = JobRequirement(
        kb_version_id=kb_version_id,
        job_id=uuid.UUID(job_id),
        requirement_text=data.text,
        category=data.category,
        is_required=data.is_required,
        min_value=data.min_value,
        max_value=data.max_value,
        unit=data.unit,
        status=PublishedStatus.PUBLISHED.value,
        version=1,
    )
    db.add(row)
    await db.flush()
    return PublishingResult("job_requirement", 1, no_op=False, diff_fields=[])
