"""Read only generic facts from a project's atomic active knowledge release."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.ingestion_template import StructuredFact


async def list_active_structured_facts(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    record_type_key: str | None = None,
) -> list[StructuredFact]:
    """Return facts only when their KB version is the project's active release."""
    statement = (
        select(StructuredFact)
        .join(Project, Project.active_kb_version_id == StructuredFact.kb_version_id)
        .where(StructuredFact.project_id == project_id)
        .order_by(StructuredFact.record_type_key, StructuredFact.created_at)
    )
    if record_type_key:
        statement = statement.where(StructuredFact.record_type_key == record_type_key)
    return list((await db.scalars(statement)).all())
