"""Active-project income summaries repository (DB layer).

Read-only verbatim income/bonus/cashflow evidence per active project for the
agent's cross-project ``compare_income`` surface. Job matching no longer lives
anywhere: the matching unit is the project, and its read belongs to
:mod:`app.services.retrieval.catalog_repository`.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Sequence

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.recruitment.domain.recommendation import ActiveProjectIncomeSummary, IncomeFeatureEvidence

_COMPARE_INCOME_FEATURE_KEYS = frozenset(
    {
        "take_home_income",
        "salary_transparency",
        "overtime_rate",
        "joining_bonus",
        "pay_frequency",
    }
)


class RecommendationRepository:
    """Read-only income evidence for the cross-project comparison tool."""

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
