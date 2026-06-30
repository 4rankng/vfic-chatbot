"""Project data access — all raw SQL + ORM lookup queries live here.

The service layer delegates to :class:`ProjectRepository` for anything that touches
``text()`` or low-level ORM select, keeping business logic in the service.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.services.errors import NotFoundError


class ProjectRepository:
    """Encapsulates raw SQL + ORM lookups used by :class:`ProjectService`."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def knowledge_document_counts(self, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not project_ids:
            return {}
        rows = (
            await self.db.execute(
                select(KnowledgeDocument.project_id, func.count(KnowledgeDocument.id))
                .where(
                    KnowledgeDocument.project_id.in_(project_ids),
                    KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
                )
                .group_by(KnowledgeDocument.project_id)
            )
        ).all()
        return {row[0]: int(row[1]) for row in rows if row[0] is not None}

    async def count_bus_routes(self, project_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    text("SELECT count(*) FROM bus_routes WHERE project_id = :pid"),
                    {"pid": str(project_id)},
                )
            ).scalar()
            or 0
        )

    async def list_bus_routes(
        self, project_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[dict]:
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, route_name, route_no, route_variant, shift, direction, "
                        "       area, mode, source_page, notes "
                        "FROM bus_routes "
                        "WHERE project_id = :pid "
                        "ORDER BY route_name ASC, shift ASC, direction ASC, route_variant ASC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    {"pid": str(project_id), "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        return list(rows)

    async def list_bus_stops(self, route_ids: list[str]) -> list[dict]:
        if not route_ids:
            return []
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, route_id, stop_order, stop_name, "
                        "       to_char(scheduled_time, 'HH24:MI') AS scheduled_time "
                        "FROM bus_stops "
                        "WHERE route_id = ANY(CAST(:route_ids AS uuid[])) "
                        "ORDER BY route_id, stop_order"
                    ),
                    {"route_ids": route_ids},
                )
            )
            .mappings()
            .all()
        )
        return list(rows)

    async def list_faq_chunks(self, project_id: uuid.UUID, *, limit: int) -> list[dict]:
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT kc.id, kc.content, kc.questions, "
                        "       kc.metadata ->> 'source_anchor' AS source_anchor, kd.file_name "
                        "FROM knowledge_chunks kc "
                        "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                        "WHERE kd.project_id = :pid "
                        "  AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                        "  AND kc.category = 'faq' "
                        "ORDER BY kc.created_at DESC, kc.chunk_index ASC "
                        "LIMIT :limit"
                    ),
                    {"pid": str(project_id), "limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return list(rows)

    async def find_by_name(self, name: str) -> Project | None:
        return (
            await self.db.scalars(
                select(Project)
                .where(func.lower(func.trim(Project.name)) == name.lower())
                .order_by(Project.created_at.asc())
                .limit(1)
            )
        ).first()

    async def get_latest_document_with_text(
        self, project_id: uuid.UUID
    ) -> KnowledgeDocument | None:
        return (
            await self.db.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.project_id == project_id,
                    KnowledgeDocument.raw_text.is_not(None),
                )
                .order_by(KnowledgeDocument.created_at.desc())
                .limit(1)
            )
        ).first()


async def require_project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    proj = await db.get(Project, project_id)
    if proj is None:
        raise NotFoundError("project not found")
    return proj
