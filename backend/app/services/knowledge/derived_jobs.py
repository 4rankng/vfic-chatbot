"""Project the current published KB into the structured ``jobs`` catalog."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.shared.domain.text import normalize_vietnamese_text
from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeStatus
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog


async def rebuild_project_jobs(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_document_id: uuid.UUID,
) -> int:
    """Make one project's jobs mirror explicit roles in its current published KB.

    The KB is the authority: present roles are ACTIVE and all other project jobs
    become unavailable. The historical status column is retained for schema
    compatibility; callers should not treat it as a second source of truth.
    """
    project = await db.get(Project, project_id)
    if project is None:
        return 0

    roles = await _current_roles(db, project)
    companies = list(
        (
            await db.scalars(
                select(Company)
                .where(Company.project_id == project_id)
                .order_by(Company.created_at, Company.id)
            )
        ).all()
    )
    company_name = str((project.index_card or {}).get("company_name") or project.name).strip()
    company = next((row for row in companies if row.name.casefold() == company_name.casefold()), None)
    if company is None and roles:
        company = Company(project_id=project_id, name=company_name or project.name, aliases=[])
        db.add(company)
        await db.flush()
        companies.append(company)

    company_ids = [row.id for row in companies]
    if company_ids:
        archive = update(Job).where(Job.company_id.in_(company_ids))
        if roles:
            archive = archive.where(func.lower(Job.title).notin_([role.casefold() for role in roles]))
        await db.execute(
            archive.values(status=JobStatus.ARCHIVED, updated_at=datetime.now(UTC))
        )

    if company is None:
        await db.commit()
        await bump_cache_version("jobs")
        return 0

    features = await _current_features(db, project_id)
    location = str((project.index_card or {}).get("location") or "").strip() or None
    highlights = (project.index_card or {}).get("highlights") or []
    benefits = "\n".join(str(item).strip() for item in highlights if str(item).strip()) or None
    salary_min, salary_max = salary_from_feature(features.get("take_home_income"))
    now = datetime.now(UTC)

    for role in roles:
        job = await db.scalar(
            select(Job).where(Job.company_id == company.id, func.lower(Job.title) == role.casefold())
        )
        values: dict[str, Any] = {
            "title": role,
            "factory_name": company.name,
            "province": location,
            "address": location,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "shift": _feature_text(features, "shift_schedule"),
            "vacancy_count": None,
            "status": JobStatus.ACTIVE,
            "description": project.summary,
            "requirements": _feature_text(features, "application_simplicity"),
            "benefits": benefits,
            "source_document_id": source_document_id,
            "updated_at": now,
        }
        if job is None:
            db.add(Job(company_id=company.id, **values))
        else:
            for field, value in values.items():
                setattr(job, field, value)

    await db.commit()
    await bump_cache_version("jobs")
    return len(roles)


async def _current_roles(db: AsyncSession, project: Project) -> list[str]:
    predicates = [
        KnowledgeDocument.project_id == project.id,
        KnowledgeDocument.status == KnowledgeStatus.PUBLISHED,
        KnowledgeChunk.category == "job",
    ]
    if project.active_kb_version_id is not None:
        predicates.append(
            or_(
                KnowledgeChunk.kb_version_id == project.active_kb_version_id,
                KnowledgeChunk.kb_version_id.is_(None),
            )
        )
    entities = (
        await db.scalars(
            select(KnowledgeChunk.entities)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(*predicates)
            .order_by(KnowledgeChunk.created_at, KnowledgeChunk.id)
        )
    ).all()
    candidates = [
        str((item or {}).get("job_title") or "").strip()
        for item in entities
        if isinstance(item, dict)
    ]
    unique: dict[str, str] = {}
    for role in candidates:
        clean = " ".join(role.split()).strip(" -–—,.;:")
        if clean:
            unique.setdefault(clean.casefold(), clean)
    return list(unique.values())


async def _current_features(db: AsyncSession, project_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    rows = (
        await db.execute(
            select(
                WorkerFeatureCatalog.feature_key,
                JobFeatureValue.value_text,
                JobFeatureValue.value_json,
            )
            .join(JobFeatureValue, JobFeatureValue.feature_id == WorkerFeatureCatalog.id)
            .where(
                JobFeatureValue.project_id == project_id,
                JobFeatureValue.is_missing.is_(False),
                JobFeatureValue.needs_clarification.is_(False),
            )
        )
    ).all()
    return {
        str(row.feature_key): {
            "value_text": str(row.value_text or "").strip(),
            "value_json": row.value_json or {},
        }
        for row in rows
    }


def _feature_text(features: dict[str, dict[str, Any]], key: str) -> str | None:
    value = str(features.get(key, {}).get("value_text") or "").strip()
    return value or None


def salary_from_feature(
    feature: dict[str, Any] | None,
) -> tuple[int | None, int | None]:
    """Project ``take_home_income`` value_json into VND ``(min, max)`` integers.

    Robust to the shapes seen in practice:
    - ``{"min": 10000000, "max": 13000000}`` (full VND ints — canonical)
    - ``{"min": "10000000", "max": "13000000"}`` (LLM-returned strings)
    - ``{"min": 7, "max": 12, "unit": "triệu VNĐ"}`` (seed-style small ints)
    - ``{}`` / missing → ``(None, None)``

    A ``unit``/``currency`` marker containing "triệu" or "million" scales small
    values (< 1000) by 1_000_000 so they reach VND. Larger values are assumed
    to already be VND.
    """
    payload = (feature or {}).get("value_json") or {}
    if not isinstance(payload, dict):
        return None, None
    # Strip Vietnamese diacritics before matching so "triệu" / "trieu" align.
    unit = normalize_vietnamese_text(str(payload.get("unit") or payload.get("currency") or ""))
    scale = 1_000_000 if ("trieu" in unit or "million" in unit) else 1
    minimum = _coerce_salary_value(payload.get("min"), scale)
    maximum = _coerce_salary_value(payload.get("max"), scale)
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum
    return minimum, maximum


def _coerce_salary_value(value: object, scale: int = 1) -> int | None:
    """Coerce a salary scalar to a VND int, tolerating strings and separators.

    Handles ints, floats, numeric strings (``"10000000"``, ``"10.000.000"``,
    ``"10,000,000"``). ``bool`` is rejected (a Python bool is an int subclass but
    is never a valid salary). Returns ``None`` when no number can be parsed.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        parsed = int(value)
    elif isinstance(value, str):
        digits = value.replace(".", "").replace(",", "").replace(" ", "").replace("₫", "")
        sign = 1
        if digits.startswith("-"):
            sign = -1
            digits = digits[1:]
        if not digits.isdigit():
            return None
        parsed = sign * int(digits)
    else:
        return None
    if parsed < 0:
        return None
    return parsed * scale if scale != 1 and parsed < 1000 else parsed
