"""Read only allowlisted generic facts from an active knowledge release."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.ingestion_template import StructuredFact

MAX_FACT_QUERY_LIMIT = 25
MAX_FACT_FILTERS = 8
MAX_VALUES_PER_IN_FILTER = 16
FilterOperator = Literal["eq", "in"]


class FactQueryError(ValueError):
    """Raised before a structured-fact query can reach the database."""


def validate_fact_query(
    artifact: dict[str, Any],
    *,
    record_type_key: str,
    filters: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Validate a closed filter language against an active compiled artifact."""
    if limit < 1 or limit > MAX_FACT_QUERY_LIMIT:
        raise FactQueryError(f"limit must be between 1 and {MAX_FACT_QUERY_LIMIT}")
    record_type = next(
        (item for item in artifact.get("record_types", []) if item.get("key") == record_type_key),
        None,
    )
    if record_type is None:
        raise FactQueryError("record type is not enabled by the active template")
    field_keys = {field["key"] for field in record_type.get("fields", [])}
    if len(filters) > MAX_FACT_FILTERS:
        raise FactQueryError(f"at most {MAX_FACT_FILTERS} filters are allowed")
    normalized: list[dict[str, Any]] = []
    for item in filters:
        if set(item) != {"field", "operator", "value"}:
            raise FactQueryError("filters must contain only field, operator, and value")
        field = item["field"]
        operator = item["operator"]
        value = item["value"]
        if not isinstance(field, str) or field not in field_keys:
            raise FactQueryError("field is not enabled by the active template")
        if operator not in {"eq", "in"}:
            raise FactQueryError("operator is not allowlisted")
        if operator == "in":
            if (
                not isinstance(value, list)
                or not value
                or len(value) > MAX_VALUES_PER_IN_FILTER
            ):
                raise FactQueryError("in filters require a non-empty bounded list")
        elif isinstance(value, (list, dict)):
            raise FactQueryError("eq filters require a scalar value")
        normalized.append({"field": field, "operator": operator, "value": value})
    return normalized


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


async def query_active_structured_facts(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    template_version_id: uuid.UUID,
    artifact: dict[str, Any],
    record_type_key: str,
    filters: list[dict[str, Any]],
    limit: int,
    as_of: datetime | None = None,
) -> list[StructuredFact]:
    """Read bounded, active-release facts through an artifact-owned schema."""
    normalized_filters = validate_fact_query(
        artifact,
        record_type_key=record_type_key,
        filters=filters,
        limit=limit,
    )
    effective_at = as_of or datetime.now(UTC)
    clauses = [
        StructuredFact.project_id == project_id,
        StructuredFact.template_version_id == template_version_id,
        StructuredFact.record_type_key == record_type_key,
        or_(StructuredFact.valid_from.is_(None), StructuredFact.valid_from <= effective_at),
        or_(StructuredFact.valid_to.is_(None), StructuredFact.valid_to >= effective_at),
    ]
    for item in normalized_filters:
        column = StructuredFact.payload[item["field"]].astext
        if item["operator"] == "eq":
            clauses.append(column == str(item["value"]))
        else:
            clauses.append(column.in_([str(value) for value in item["value"]]))
    statement = (
        select(StructuredFact)
        .join(Project, Project.active_kb_version_id == StructuredFact.kb_version_id)
        .where(and_(*clauses))
        .order_by(StructuredFact.record_type_key, StructuredFact.created_at, StructuredFact.id)
        .limit(limit)
    )
    return list((await db.scalars(statement)).all())
