"""Job recommendation and active recruitment catalog repository (DB layer).

Two-stage ranker over the existing ``jobs`` table — no new tables, no migrations:

* Stage 1 (SQL WHERE): hard business filters — ACTIVE status, salary band overlap,
  vacancy > 0, optional province / age / gender gates.
* Stage 2 (Python, :mod:`.scoring`): weighted scoring + matched reasons.

Profile matching uses structured ``jobs`` rows. The generic active catalog also
projects recruiter-authored discovery cards from ready single-page Projects so
both supported knowledge modes can advertise their current opportunities.
"""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, Project
from app.models.job import Job
from app.models.job import JobStatus
from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.recruitment.domain.recommendation import ActiveProjectIncomeSummary, IncomeFeatureEvidence
from app.services.knowledge.derived_jobs import salary_from_feature
from app.services.recommendation.availability import (
    ActiveJob,
    ActiveJobLookup,
    SortBy,
    select_matching_active_jobs,
)
from app.services.recommendation.scoring import JobCandidate, LeadProfile, ScoredJob, score_job

logger = logging.getLogger(__name__)

_COMPARE_INCOME_FEATURE_KEYS = frozenset(
    {
        "take_home_income",
        "salary_transparency",
        "overtime_rate",
        "joining_bonus",
        "pay_frequency",
    }
)

# Stage-1 candidate fetch. Filters are deliberately loose (status + vacancy) so the
# Python scorer can weigh the rest; tightening here risks dropping jobs that fail a
# soft signal (e.g. age) but pass everything else. Optional province filter is the
# one hard location gate — a candidate saying "Bình Dương" should never see Hà Nội.
_MATCH_SQL = text(
    """
    SELECT
        j.id, j.title, j.factory_name, j.province, j.district,
        j.salary_min, j.salary_max, j.shift,
        j.age_min, j.age_max, j.gender_requirement,
        j.experience_required,
        j.accommodation_support, j.meal_support, j.transport_support,
        j.vacancy_count
    FROM jobs j
    JOIN companies c ON c.id = j.company_id
    JOIN projects p ON p.id = c.project_id
    WHERE j.status = :status
      AND COALESCE(j.vacancy_count, 1) > 0
      AND (
        (p.category_authority_started AND j.source_category_revision_id IS NOT NULL)
        OR
        (NOT p.category_authority_started AND j.source_category_revision_id IS NULL)
      )
      AND (CAST(:province AS text) IS NULL
           OR normalize_search_text(j.province) ILIKE normalize_search_text(CAST(:province AS text))
           OR normalize_search_text(j.district) ILIKE normalize_search_text(CAST(:province AS text)))
      AND (CAST(:pids_active AS boolean) IS NOT TRUE
           OR (p.is_active AND p.id = ANY(CAST(:pids AS uuid[]))))
    ORDER BY j.updated_at DESC
    LIMIT :limit
    """
)


def _card_items(value: object) -> list[str]:
    """Normalize recruiter-authored discovery-card values into clean text items."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple):
        values = [item for item in value if isinstance(item, str)]
    else:
        return []
    return [text for item in values if (text := " ".join(item.split()))]


def _direct_project_active_job(
    project: Project,
    *,
    salary: tuple[int | None, int | None] | None = None,
) -> ActiveJob | None:
    """Expose one ready single-page Project through the vacancy catalog.

    The discovery card is the compact, recruiter-authored catalog authority. Salary
    comes from the caller-resolved source (``job_feature_values`` projected via
    :func:`salary_from_feature`, or the discovery card's ``salary_min_vnd`` /
    ``salary_max_vnd`` fallback). Other structured fields stay empty rather than
    parsed from free text.
    """
    card = project.index_card or {}
    roles = _card_items(card.get("roles") or card.get("key_roles"))
    if not roles:
        return None
    location = " / ".join(_card_items(card.get("location")))
    highlights = _card_items(card.get("highlights"))
    eligibility = _card_items(card.get("eligibility"))
    title = " / ".join(roles)
    salary_min, salary_max = _resolve_direct_salary(project, card, salary)
    return ActiveJob(
        id=str(project.id),
        title=title,
        company_name=project.name,
        factory_name=project.name,
        province=location,
        salary_min=salary_min,
        salary_max=salary_max,
        company_aliases=tuple(project.aliases or ()),
        project_name=project.name,
        project_slug=project.slug,
        address=location,
        description=str(project.summary or ""),
        requirements="\n".join(eligibility),
        benefits="\n".join(highlights),
        # DIRECT_CONTEXT synthesized jobs have no row-level timestamp; the project's
        # last refresh is the closest proxy for "when was this posted".
        created_at=project.updated_at,
    )


def _resolve_direct_salary(
    project: Project,
    card: dict[str, Any],
    salary: tuple[int | None, int | None] | None,
) -> tuple[int | None, int | None]:
    """Pick a salary source for a DIRECT_CONTEXT project.

    Priority: caller-provided feature-derived salary > discovery card VND fields.
    Returns ``(None, None)`` when neither source has data — the agent then answers
    "tin tuyển dụng chưa ghi rõ" instead of inventing a figure.
    """
    if salary is not None:
        minimum, maximum = salary
        if minimum is not None or maximum is not None:
            return minimum, maximum
    card_min = _int_or_none(card.get("salary_min_vnd"))
    card_max = _int_or_none(card.get("salary_max_vnd"))
    return card_min, card_max


def _int_or_none(value: Any) -> int | None:
    """Best-effort int coercion for discovery-card salary fields."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, str):
            digits = value.replace(".", "").replace(",", "").strip()
            return int(digits) if digits.isdigit() else None
        if isinstance(value, int | float):
            parsed = int(value)
            return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None
    return None


def _interleave_catalog_sources(
    direct_jobs: list[ActiveJob], structured_jobs: list[ActiveJob]
) -> list[ActiveJob]:
    """Keep both knowledge modes represented in a bounded generic response."""
    combined: list[ActiveJob] = []
    for index in range(max(len(direct_jobs), len(structured_jobs))):
        if index < len(direct_jobs):
            combined.append(direct_jobs[index])
        if index < len(structured_jobs):
            combined.append(structured_jobs[index])
    return combined


async def _direct_project_salaries(
    db: AsyncSession, project_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int | None, int | None]]:
    """Batch-fetch ``take_home_income`` salaries for DIRECT_CONTEXT projects.

    Returns ``{project_id: (salary_min, salary_max)}`` parsed via
    :func:`salary_from_feature`, robust to string-typed or unit-marked values.
    """
    if not project_ids:
        return {}
    rows = (
        await db.execute(
            select(
                JobFeatureValue.project_id,
                JobFeatureValue.value_json,
            )
            .join(
                WorkerFeatureCatalog,
                WorkerFeatureCatalog.id == JobFeatureValue.feature_id,
            )
            .where(
                JobFeatureValue.project_id.in_(project_ids),
                WorkerFeatureCatalog.feature_key == "take_home_income",
                JobFeatureValue.is_missing.is_(False),
            )
        )
    ).all()
    salaries: dict[uuid.UUID, tuple[int | None, int | None]] = {}
    for row in rows:
        pid = row.project_id
        if pid in salaries:
            continue
        salaries[pid] = salary_from_feature({"value_json": row.value_json or {}})
    return salaries


class RecommendationRepository:
    """Read-only structured job matching against a candidate lead profile."""

    CANDIDATE_LIMIT = 100  # Stage-1 fetch ceiling; scorer truncates to top_k.

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def income_summary_for_active_projects(
        self, project_ids: Sequence[str] | None = None
    ) -> tuple[ActiveProjectIncomeSummary, ...]:
        """Return relevant verbatim income evidence for every active project.

        One bounded ORM query joins active projects to the worker-feature rows the
        chatbot may cite for cross-project salary/income comparisons. Grouping and
        formatting stay in Python so the graph can preserve verbatim evidence while
        keeping routing/tool selection deterministic.

        ``project_ids`` optionally restricts the compared set (Page-scoped
        multi-Page catalogs); ``None`` keeps the deployment-wide default.
        """
        active_projects_stmt = (
            select(
                Project.id.label("project_id"),
                Project.slug.label("project_slug"),
                Project.name.label("project_name"),
            )
            .where(Project.is_active.is_(True))
            .order_by(Project.name.asc(), Project.id.asc())
        )
        if project_ids is not None:
            active_projects_stmt = active_projects_stmt.where(
                Project.id.in_([uuid.UUID(str(pid)) for pid in project_ids])
            )
        active_projects = active_projects_stmt.subquery()
        rows = (
            await self.db.execute(
                select(
                    active_projects.c.project_id,
                    active_projects.c.project_slug,
                    active_projects.c.project_name,
                    WorkerFeatureCatalog.feature_key,
                    WorkerFeatureCatalog.category,
                    WorkerFeatureCatalog.name_vi,
                    JobFeatureValue.value_text,
                    JobFeatureValue.is_missing,
                    JobFeatureValue.needs_clarification,
                )
                .select_from(active_projects)
                .join(
                    JobFeatureValue,
                    JobFeatureValue.project_id == active_projects.c.project_id,
                )
                .join(
                    WorkerFeatureCatalog,
                    WorkerFeatureCatalog.id == JobFeatureValue.feature_id,
                )
                .where(
                    WorkerFeatureCatalog.is_active.is_(True),
                    WorkerFeatureCatalog.feature_key.in_(_COMPARE_INCOME_FEATURE_KEYS),
                    WorkerFeatureCatalog.category.in_(("income", "bonus", "cashflow")),
                    JobFeatureValue.is_missing.is_(False),
                    JobFeatureValue.needs_clarification.is_(False),
                    JobFeatureValue.value_text.is_not(None),
                )
                .order_by(
                    active_projects.c.project_name.asc(),
                    active_projects.c.project_id.asc(),
                    case(
                        (WorkerFeatureCatalog.category == "income", 0),
                        (WorkerFeatureCatalog.category == "bonus", 1),
                        (WorkerFeatureCatalog.category == "cashflow", 2),
                        else_=3,
                    ),
                    JobFeatureValue.display_priority.asc(),
                    WorkerFeatureCatalog.default_importance_score.desc(),
                    WorkerFeatureCatalog.feature_key.asc(),
                )
            )
        ).all()
        summaries: OrderedDict[str, dict[str, object]] = OrderedDict()
        for row in rows:
            project_id = str(row.project_id)
            summary = summaries.setdefault(
                project_id,
                {
                    "project_slug": str(row.project_slug or ""),
                    "project_name": str(row.project_name or ""),
                    "evidence": [],
                },
            )
            evidence = summary["evidence"]
            assert isinstance(evidence, list)
            evidence.append(
                IncomeFeatureEvidence(
                    feature_key=str(row.feature_key),
                    category=str(row.category or ""),
                    name_vi=str(row.name_vi or row.feature_key),
                    value_text=str(row.value_text),
                    is_missing=bool(row.is_missing),
                    needs_clarification=bool(row.needs_clarification),
                )
            )
        return tuple(
            ActiveProjectIncomeSummary(
                project_id=project_id,
                project_slug=str(summary["project_slug"]),
                project_name=str(summary["project_name"]),
                evidence=tuple(summary["evidence"]),
            )
            for project_id, summary in summaries.items()
        )

    async def match_jobs(
        self,
        lead: LeadProfile,
        *,
        top_k: int = 5,
        province: str | None = None,
        project_ids: Sequence[str] | None = None,
    ) -> list[ScoredJob]:
        """Return up to ``top_k`` ACTIVE jobs ranked by fit against the lead.

        ``province`` forces a hard location gate (recommended when the lead states one);
        pass ``None`` to search nationwide (cold start with no location signal).

        ``project_ids`` restricts the candidate set (Page-scoped multi-Page
        catalogs); ``None`` searches deployment-wide (single-Page/Zalo default).
        The scoped predicate also enforces ``p.is_active`` so a deactivated
        Project never leaks through a stale mapping.
        """
        gate = province or lead.living_area or lead.region or None
        # Both scope parameters are always bound: SQLAlchemy's text() requires a
        # value for every placeholder in the statement, so omitting them on the
        # unscoped path raised "A value is required for bind parameter
        # 'pids_active'" instead of searching deployment-wide.
        params: dict[str, Any] = {
            "status": JobStatus.ACTIVE.value,
            "province": gate,
            "limit": self.CANDIDATE_LIMIT,
            "pids_active": project_ids is not None,
            "pids": [str(pid) for pid in project_ids] if project_ids is not None else [],
        }
        result = await self.db.execute(_MATCH_SQL, params)
        rows = [dict(r._mapping) for r in result.fetchall()]

        scored = [score_job(lead, JobCandidate.from_row(row)) for row in rows]
        scored.sort(key=lambda s: (-s.score, s.job.title))
        return scored[: max(1, min(top_k, 10))]

    async def list_active_jobs(
        self,
        *,
        role: str | None = None,
        company: str | None = None,
        location: str | None = None,
        top_k: int = 3,
        project_ids: Sequence[str] | None = None,
        sort_by: SortBy | None = None,
    ) -> ActiveJobLookup:
        """List scoped open opportunities satisfying explicit semantic filters.

        This is intentionally separate from profile-based recommendations: no lead
        data is required. Structured Job rows and active, ready single-page Project
        cards share this catalog. An empty/unconfigured catalog, a genuine no-match,
        and a database failure remain distinct so the graph can choose the right
        authority.
        """
        if project_ids == []:
            return ActiveJobLookup("catalog_empty")
        try:
            predicates = [
                Job.status == JobStatus.ACTIVE,
                func.coalesce(Job.vacancy_count, 1) > 0,
                Project.is_active.is_(True),
                or_(
                    and_(
                        Project.category_authority_started.is_(True),
                        Job.source_category_revision_id.is_not(None),
                    ),
                    and_(
                        Project.category_authority_started.is_(False),
                        Job.source_category_revision_id.is_(None),
                    ),
                ),
            ]
            if project_ids is not None:
                predicates.append(Company.project_id.in_(project_ids))
            rows = (
                await self.db.execute(
                    select(
                        Job,
                        Company.name,
                        Company.aliases,
                        Project.name,
                        Project.slug,
                        Project.id,
                    )
                    .join(Company, Job.company_id == Company.id)
                    .join(Project, Company.project_id == Project.id)
                    .where(*predicates)
                    .order_by(Job.updated_at.desc(), Job.id.asc())
                    .limit(self.CANDIDATE_LIMIT)
                )
            ).all()
            direct_predicates = [
                Project.is_active.is_(True),
                KnowledgeBase.mode == KnowledgeBaseMode.DIRECT_CONTEXT,
            ]
            if project_ids is not None:
                direct_predicates.append(Project.id.in_(project_ids))
            direct_projects = list(
                (
                    await self.db.execute(
                        select(Project)
                        .join(KnowledgeBase, KnowledgeBase.id == Project.knowledge_base_id)
                        .join(
                            KnowledgeBaseDirectFile,
                            KnowledgeBaseDirectFile.knowledge_base_id == KnowledgeBase.id,
                        )
                        .where(*direct_predicates)
                        .order_by(Project.updated_at.desc(), Project.id.asc())
                        .limit(self.CANDIDATE_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
            structured_project_ids = {str(row[5]) for row in rows}
            direct_salaries = await _direct_project_salaries(
                self.db, [project.id for project in direct_projects]
            )
            direct_jobs = [
                job
                for project in direct_projects
                if str(project.id) not in structured_project_ids
                and (
                    job := _direct_project_active_job(
                        project, salary=direct_salaries.get(project.id)
                    )
                )
                is not None
            ]
            if not rows and not direct_jobs:
                catalog_query = (
                    select(Job.id)
                    .join(Company, Job.company_id == Company.id)
                    .join(Project, Company.project_id == Project.id)
                    .where(
                        Project.is_active.is_(True),
                        or_(
                            and_(
                                Project.category_authority_started.is_(True),
                                Job.source_category_revision_id.is_not(None),
                            ),
                            and_(
                                Project.category_authority_started.is_(False),
                                Job.source_category_revision_id.is_(None),
                            ),
                        ),
                    )
                )
                if project_ids is not None:
                    catalog_query = catalog_query.where(Company.project_id.in_(project_ids))
                catalog_probe = await self.db.execute(
                    catalog_query.limit(1)
                )
                if catalog_probe.scalar_one_or_none() is not None:
                    return ActiveJobLookup("no_match")
                return ActiveJobLookup("catalog_empty")
        except Exception:
            logger.warning("active-job availability lookup failed", exc_info=True)
            try:
                await self.db.rollback()
            except Exception:  # noqa: BLE001 — preserve the candidate-facing unavailable reply
                logger.debug("active-job availability rollback failed", exc_info=True)
            return ActiveJobLookup("unavailable")

        jobs = [
            ActiveJob(
                id=str(job.id),
                title=job.title,
                company_name=str(company_name),
                factory_name=job.factory_name or "",
                province=job.province or "",
                district=job.district or "",
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                vacancy_count=job.vacancy_count,
                company_aliases=tuple(company_aliases or ()),
                project_name=str(project_name or ""),
                project_slug=str(project_slug or ""),
                address=str(getattr(job, "address", "") or ""),
                shift=str(getattr(job, "shift", "") or ""),
                gender_requirement=str(getattr(job, "gender_requirement", "") or ""),
                age_min=getattr(job, "age_min", None),
                age_max=getattr(job, "age_max", None),
                experience_required=str(getattr(job, "experience_required", "") or ""),
                accommodation_support=getattr(job, "accommodation_support", None),
                meal_support=getattr(job, "meal_support", None),
                transport_support=getattr(job, "transport_support", None),
                description=str(getattr(job, "description", "") or ""),
                requirements=str(getattr(job, "requirements", "") or ""),
                benefits=str(getattr(job, "benefits", "") or ""),
                created_at=getattr(job, "created_at", None),
            )
            for job, company_name, company_aliases, project_name, project_slug, _project_id in rows
        ]
        # Interleave sources so a bounded generic response represents both
        # knowledge modes. A Project that already supplied a structured Job was
        # removed above.
        jobs = _interleave_catalog_sources(direct_jobs, jobs)
        return select_matching_active_jobs(
            jobs,
            role=role,
            company=company,
            location=location,
            top_k=top_k,
            sort_by=sort_by,
        )


LeadRecommendationStatus = Literal["matched", "no_match", "insufficient_profile", "unavailable"]


@dataclass(frozen=True)
class LeadJobRecommendation:
    """Typed profile-based recommendation outcome for the graph tool."""

    status: LeadRecommendationStatus
    jobs: tuple[ScoredJob, ...] = ()
