"""Safe bridge from reviewed recruitment extraction to typed authority rows.

Job identity is never inferred from text. A caller must supply an existing UUID
whose company belongs to the KB project; the adapter never changes operational
job fields such as status, vacancies, or salary.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.job import Job
from app.schemas.extraction_contracts import ExtractionEnvelope
from app.services.knowledge.publishing.publisher import (
    PublishingError,
    PublishingResult,
    publish_contract,
)


async def resolve_stable_job_id(
    db: AsyncSession, *, project_id: uuid.UUID, job_id: str | None
) -> str:
    """Accept only a real project-owned job UUID; no title/name fuzzy matching."""
    if not job_id:
        raise PublishingError("recruitment fact requires an explicit job_id mapping")
    try:
        parsed = uuid.UUID(job_id)
    except ValueError as exc:
        raise PublishingError("job_id mapping must be a UUID") from exc
    row = await db.scalar(
        select(Job.id)
        .join(Company, Company.id == Job.company_id)
        .where(Job.id == parsed, Company.project_id == project_id)
    )
    if row is None:
        raise PublishingError("job_id is not an existing job in this KB project")
    return str(row)


async def publish_reviewed_recruitment_contract(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    kb_version_id: uuid.UUID,
    envelope: ExtractionEnvelope,
    job_id: str | None,
) -> PublishingResult:
    """Stage a typed recruitment fact under a KB release after stable resolution."""
    entity_type = envelope.data.entity_type
    resolved_job_id = None
    if entity_type in {"job_requirement", "benefit"} and envelope.scope.type == "job_posting":
        resolved_job_id = await resolve_stable_job_id(db, project_id=project_id, job_id=job_id)
    return await publish_contract(
        db,
        envelope,
        job_id=resolved_job_id,
        kb_version_id=str(kb_version_id),
    )
