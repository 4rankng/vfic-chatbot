"""Project-catalog, persona, and recruitment-feature reads for the agent.

The catalog owns the Page-scoped project surfaces (slug resolution, active
project listings, the master-index card set) plus the per-project job-feature
rows. ``list_active_projects`` is the matching authority's read: every active
project as rich fit features (scope, location, salary), which the graph tool
ranks against the candidate's stated preferences.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, Project
from app.models.job import Job, JobStatus
from app.models.knowledge import KnowledgeCategory
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.recruitment.domain.recommendation import ProjectFeatures, ProjectScopeItem
from app.services.knowledge.category_contracts import validate_category_payload
from app.services.knowledge.category_projections import render_category_units
from app.services.knowledge.derived_jobs import salary_from_feature
from app.services.recommendation import RecommendationRepository

logger = logging.getLogger(__name__)

# Padding around the projects' bounding box for the area-lookup viewbox, in
# degrees (~38 km at Vietnam's latitude): the box must comfortably contain the
# landmarks candidates name near the projects, not only the projects themselves.
_VIEWBOX_MARGIN_DEGREES = 0.35


def _card_items(value: object) -> list[str]:
    """Normalize recruiter-authored discovery-card values into clean text items."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple):
        values = [item for item in value if isinstance(item, str)]
    else:
        return []
    return [text for item in values if (text := " ".join(item.split()))]


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


async def _direct_project_salaries(
    db: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int | None, int | None]]:
    """Batch-fetch ``take_home_income`` salaries for card-only projects.

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


def _resolve_direct_salary(
    card: dict[str, Any],
    salary: tuple[int | None, int | None] | None,
) -> tuple[int | None, int | None]:
    """Pick a salary source for a card-only project.

    Priority: feature-derived salary > discovery card VND fields.
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


class CatalogRepository:
    """Read-only project/persona catalog queries, optionally Page-scoped."""

    def __init__(self, db: AsyncSession, *, page_project_ids: tuple[str, ...] | None) -> None:
        self.db = db
        # Page-scoped catalog for multi-Page Facebook: when set, the Project
        # catalog surfaces (active_project_ids, active_projects_with_card,
        # list_active_projects, project_id_by_slug, income_summary_for_active_projects)
        # are restricted to the Facebook Page's assigned Project set. None →
        # deployment-wide (Zalo + legacy).
        self.page_project_ids: tuple[str, ...] | None = page_project_ids

    async def project_id_by_slug(self, slug: str, *, active_only: bool = False) -> uuid.UUID | None:
        """Resolve a project id from its (unique) slug; optionally require ``is_active``.

        Deliberately NOT scoped to the Page's linked projects: a candidate who
        names a project is making an explicit request, and the bot must be able
        to consult (and measure distances to) any active project — the linked
        set is the starting point, not the ceiling (2026-10-07).
        """
        sql = "SELECT p.id FROM projects p WHERE p.slug = :s AND p.knowledge_base_id IS NOT NULL"
        if active_only:
            sql += " AND p.is_active"
        pid = (await self.db.execute(text(sql), {"s": slug})).scalar_one_or_none()
        return pid

    async def load_category_knowledge(self, project_ids: list[str], category_key: str) -> list[Any]:
        """Rendered whole-category text for the agent's deep-load tool.

        One row per (project, category) that has an ACTIVE revision in scope:
        ``(slug, category_key, text)`` where ``text`` is every record of the
        revision rendered through the same category projections the retrieval
        chunks and the activation selftest judge — the agent reads exactly the
        content the knowledge pipeline publishes, not a re-summary.
        ``category_key="all"`` returns every category carrying data.
        """
        sql = text(
            "SELECT p.slug AS slug, kc.category_key AS category_key, "
            "kcr.normalized_payload AS payload "
            "FROM knowledge_categories kc "
            "JOIN projects p ON p.id = kc.project_id AND p.is_active IS TRUE "
            "JOIN knowledge_category_revisions kcr ON kcr.id = kc.active_revision_id "
            "WHERE kc.project_id = ANY(:ids) "
            "AND (:category = 'all' OR kc.category_key = :category) "
            "ORDER BY p.name, kc.category_key"
        )
        rows = (await self.db.execute(sql, {"ids": project_ids, "category": category_key})).all()
        rendered: list[Any] = []
        for row in rows:
            try:
                document = validate_category_payload(row.category_key, row.payload)
                units = render_category_units(document)
            except Exception:  # noqa: BLE001 - one bad revision must not kill the load
                logger.warning(
                    "category knowledge render failed project=%s category=%s",
                    row.slug,
                    row.category_key,
                    exc_info=True,
                )
                continue
            body = "\n\n".join(unit["content"] for unit in units if unit.get("content"))
            rendered.append(
                SimpleNamespace(slug=row.slug, category_key=row.category_key, text=body)
            )
        return rendered

    async def active_area_viewbox(self) -> str | None:
        """The active projects' bounding box as an ``x1,y1,x2,y2`` viewbox string.

        Candidate area lookups are often bare landmark names ("Núi Đèo") that
        the provider resolves nationwide — the 2026-10-02 incident resolved one
        to a same-named feature ~120 km from every project, and the catalog
        then reported confidently wrong distances. Handing the provider the box
        the projects actually occupy biases its ranking toward that region
        without excluding anything, so a genuinely-far candidate area still
        resolves truthfully. ``None`` when no project has coordinates.

        Bias-only by design: ``bounded=1`` would turn the box into a filter and
        force far queries to match whatever sits inside it.
        """
        row = (
            await self.db.execute(
                select(
                    func.min(Project.latitude),
                    func.max(Project.latitude),
                    func.min(Project.longitude),
                    func.max(Project.longitude),
                ).where(
                    Project.is_active.is_(True),
                    Project.latitude.is_not(None),
                    Project.longitude.is_not(None),
                )
            )
        ).one()
        min_lat, max_lat, min_lng, max_lng = row
        if min_lat is None or min_lng is None:
            return None
        margin = _VIEWBOX_MARGIN_DEGREES
        return (
            f"{max(min_lng - margin, -180.0):.4f},{min(max_lat + margin, 90.0):.4f},"
            f"{min(max_lng + margin, 180.0):.4f},{max(min_lat - margin, -90.0):.4f}"
        )

    async def list_active_projects(self) -> list[ProjectFeatures]:
        """Every active KB-backed project as rich fit features — never capped.

        One :class:`ProjectFeatures` row per active project: structured scope
        items from the project's open Job rows (scope predicate copied from the
        retired job matcher: ACTIVE status, the vacancy rule, the
        category-authority consistency rule), or — for card-only projects —
        scope/location from the discovery card and salary from the
        ``take_home_income`` feature values (card VND fields as fallback). DB
        errors propagate: the tool maps them to ``unavailable``.
        """
        project_predicates = [
            Project.is_active.is_(True),
            Project.knowledge_base_id.is_not(None),
        ]
        linked_ids = (
            [uuid.UUID(pid) for pid in self.page_project_ids]
            if self.page_project_ids is not None
            else None
        )
        project_rows = (
            await self.db.execute(
                select(
                    Project.id,
                    Project.slug,
                    Project.name,
                    Project.summary,
                    Project.index_card,
                    Project.aliases,
                    Project.updated_at,
                    Project.latitude,
                    Project.longitude,
                )
                .where(*project_predicates)
                # Page-linked projects are the STARTING POINT of the catalog,
                # never its ceiling (operator directive 2026-10-07): the whole
                # active catalog is returned so the bot can consult other
                # projects when asked, with the linked ones ranked first.
                .order_by(
                    case((Project.id.in_(linked_ids or []), 0), else_=1),
                    Project.name.asc(),
                    Project.id.asc(),
                )
            )
        ).all()
        if not project_rows:
            return []
        project_ids = [row.id for row in project_rows]

        job_rows = (
            await self.db.execute(
                select(
                    Job.title,
                    Job.salary_min,
                    Job.salary_max,
                    Job.province,
                    Job.district,
                    Job.address,
                    Job.factory_name,
                    Company.name.label("company_name"),
                    Company.project_id.label("project_id"),
                )
                .join(Company, Company.id == Job.company_id)
                .join(Project, Project.id == Company.project_id)
                .where(
                    Company.project_id.in_(project_ids),
                    Job.status == JobStatus.ACTIVE,
                    func.coalesce(Job.vacancy_count, 1) > 0,
                    or_(
                        and_(
                            Project.category_authority_started.is_(True),
                            select(KnowledgeCategory.id)
                            .where(
                                KnowledgeCategory.project_id == Project.id,
                                KnowledgeCategory.category_key == "jobs",
                                KnowledgeCategory.active_revision_id
                                == Job.source_category_revision_id,
                            )
                            .exists(),
                        ),
                        and_(
                            Project.category_authority_started.is_(False),
                            Job.source_category_revision_id.is_(None),
                        ),
                    ),
                )
                .order_by(Job.updated_at.desc(), Job.id.asc())
            )
        ).all()

        scope_by_project: dict[uuid.UUID, list[ProjectScopeItem]] = {}
        meta_by_project: dict[uuid.UUID, dict[str, Any]] = {}
        for row in job_rows:
            scope_by_project.setdefault(row.project_id, []).append(
                ProjectScopeItem(
                    title=str(row.title or ""),
                    salary_min=row.salary_min,
                    salary_max=row.salary_max,
                )
            )
            meta = meta_by_project.setdefault(row.project_id, {})
            meta.setdefault("company", str(row.company_name or ""))
            for key, attr in (
                ("factory", "factory_name"),
                ("province", "province"),
                ("district", "district"),
                ("address", "address"),
            ):
                if not meta.get(key):
                    meta[key] = str(getattr(row, attr) or "")

        card_only_ids = [pid for pid in project_ids if pid not in scope_by_project]
        card_salaries = await _direct_project_salaries(self.db, card_only_ids)

        features: list[ProjectFeatures] = []
        for row in project_rows:
            scope = scope_by_project.get(row.id)
            if scope is not None:
                meta = meta_by_project.get(row.id, {})
                salary_min = min(
                    (item.salary_min for item in scope if item.salary_min is not None),
                    default=None,
                )
                salary_max = max(
                    (item.salary_max for item in scope if item.salary_max is not None),
                    default=None,
                )
                features.append(
                    ProjectFeatures(
                        project_id=str(row.id),
                        slug=str(row.slug or ""),
                        name=str(row.name or ""),
                        company=meta.get("company", ""),
                        factory=meta.get("factory", ""),
                        province=meta.get("province", ""),
                        district=meta.get("district", ""),
                        address=meta.get("address", ""),
                        summary=str(row.summary or ""),
                        updated_at=row.updated_at,
                        salary_min=salary_min,
                        salary_max=salary_max,
                        scope=tuple(scope),
                        aliases=tuple(_card_items(getattr(row, "aliases", None))),
                        latitude=row.latitude,
                        longitude=row.longitude,
                    )
                )
                continue
            card = row.index_card or {}
            roles = _card_items(card.get("roles") or card.get("key_roles"))
            location = " / ".join(_card_items(card.get("location")))
            salary_min, salary_max = _resolve_direct_salary(card, card_salaries.get(row.id))
            features.append(
                ProjectFeatures(
                    project_id=str(row.id),
                    slug=str(row.slug or ""),
                    name=str(row.name or ""),
                    company=str(row.name or ""),
                    province=location,
                    summary=str(row.summary or ""),
                    updated_at=row.updated_at,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    scope=tuple(ProjectScopeItem(title=role) for role in roles),
                    aliases=tuple(_card_items(getattr(row, "aliases", None))),
                    latitude=row.latitude,
                    longitude=row.longitude,
                )
            )
        return features

    async def active_projects_with_card(self) -> list:
        """Active projects for the master-index prompt."""
        if self.page_project_ids is not None:
            return list(
                (
                    await self.db.execute(
                        text(
                            "SELECT p.name, p.slug, p.summary, p.index_card, p.aliases "
                            "FROM projects p "
                            "WHERE p.is_active AND p.knowledge_base_id IS NOT NULL "
                            "AND p.id = ANY(CAST(:pids AS uuid[])) ORDER BY p.name"
                        ),
                        {"pids": list(self.page_project_ids)},
                    )
                ).all()
            )
        return list(
            (
                await self.db.execute(
                    text(
                        "SELECT p.name, p.slug, p.summary, p.index_card, p.aliases "
                        "FROM projects p "
                        "WHERE p.is_active AND p.knowledge_base_id IS NOT NULL ORDER BY p.name"
                    )
                )
            ).all()
        )

        return (
            await self.db.execute(
                text(
                    "SELECT body_md FROM personas WHERE is_active ORDER BY updated_at DESC LIMIT 1"
                )
            )
        ).scalar_one_or_none()

    async def active_project_ids(self) -> list[str]:
        """Active KB-backed project ids: the Page's assigned set when scoped
        for multi-Page Facebook, else the deployment-wide catalog."""
        statement = select(Project.id).where(
            Project.is_active.is_(True),
            Project.knowledge_base_id.is_not(None),
        )
        if self.page_project_ids is not None:
            if not self.page_project_ids:
                return []
            statement = statement.where(
                Project.id.in_([uuid.UUID(pid) for pid in self.page_project_ids])
            )
        rows = await self.db.scalars(statement.order_by(Project.id))
        return [str(pid) for pid in rows]

    async def project_ids_for_page(self, account_key: str) -> list[str]:
        """Assigned Project ids for one channel account (e.g. a Facebook Page).

        Returns the raw assignment set (no ``is_active`` filter): catalog
        queries apply their own active filters, and the activation gate counts
        only ACTIVE-project mappings. Used by the graph layer to bind a
        conversation's Page scope onto the retrieval port.
        """
        from app.models.channel_account import ChannelAccount, ChannelAccountProject

        rows = (
            await self.db.execute(
                select(ChannelAccountProject.project_id)
                .join(
                    ChannelAccount,
                    ChannelAccount.id == ChannelAccountProject.channel_account_id,
                )
                .where(ChannelAccount.account_key == account_key)
                .order_by(ChannelAccountProject.created_at.asc())
            )
        ).scalars()
        return [str(pid) for pid in rows]

    async def job_features_for_project(self, project_id: uuid.UUID) -> list:
        """A project's active worker features in catalog display order.

        Filtered to ``is_active`` catalog rows so disabled criteria (migration 0009) are
        hidden from the agent tool and readiness gauge without re-extraction.
        """
        statement = (
            select(
                JobFeatureValue.value_text,
                JobFeatureValue.value_json,
                JobFeatureValue.is_highlight,
                JobFeatureValue.is_missing,
                JobFeatureValue.needs_clarification,
                JobFeatureValue.evidence_text,
                WorkerFeatureCatalog.name_vi,
                WorkerFeatureCatalog.feature_key,
            )
            .join(
                WorkerFeatureCatalog,
                WorkerFeatureCatalog.id == JobFeatureValue.feature_id,
            )
            .where(
                JobFeatureValue.project_id == project_id,
                WorkerFeatureCatalog.is_active.is_(True),
            )
            .order_by(
                JobFeatureValue.display_priority.asc(),
                WorkerFeatureCatalog.default_importance_score.desc(),
            )
        )
        return list((await self.db.execute(statement)).all())

    async def income_summary_for_active_projects(self):
        """Verbatim income evidence for active projects (Page-scoped when bound)."""
        scope = list(self.page_project_ids) if self.page_project_ids is not None else None
        return await RecommendationRepository(self.db).income_summary_for_active_projects(scope)
