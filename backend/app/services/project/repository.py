"""Project data access — all raw SQL + ORM lookup queries live here.

The service layer delegates to :class:`ProjectRepository` for anything that touches
``text()`` or low-level ORM select, keeping business logic in the service.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, Project
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeStatus
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

    async def get_faq_chunk(self, project_id: uuid.UUID, chunk_id: uuid.UUID) -> dict | None:
        row = (
            (
                await self.db.execute(
                    text(
                        "SELECT kc.id, kc.document_id, kc.content, kc.questions, "
                        "       kc.metadata ->> 'source_anchor' AS source_anchor, kd.file_name "
                        "FROM knowledge_chunks kc "
                        "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                        "WHERE kd.project_id = :pid "
                        "  AND kc.id = :cid "
                        "  AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                        "  AND kc.category = 'faq' "
                        "LIMIT 1"
                    ),
                    {"pid": str(project_id), "cid": str(chunk_id)},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def next_faq_chunk_index(self, document_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    text(
                        "SELECT COALESCE(MAX(chunk_index), -1) + 1 "
                        "FROM knowledge_chunks WHERE document_id = :did"
                    ),
                    {"did": str(document_id)},
                )
            ).scalar()
            or 0
        )

    async def managed_faq_document(self, project: Project) -> KnowledgeDocument:
        existing = (
            await self.db.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.project_id == project.id,
                    KnowledgeDocument.source == "faq_editor",
                    KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
                )
                .order_by(KnowledgeDocument.created_at.asc())
                .limit(1)
            )
        ).first()
        if existing:
            return existing

        company = (
            await self.db.scalars(
                select(Company)
                .where(Company.project_id == project.id)
                .order_by(Company.created_at.asc())
                .limit(1)
            )
        ).first()
        company_name = company.name if company else "VFIC"

        doc = KnowledgeDocument(
            file_name=f"{project.slug}-faq-editor.md",
            source="faq_editor",
            version="1.0",
            status=KnowledgeStatus.PUBLISHED,
            raw_text="",
            metadata_={
                "schema_version": "vfic-faq-v1",
                "doc_id": f"{project.slug}_faq_editor",
                "doc_version": "1.0",
                "title": f"FAQ {project.name}",
                "company_name": company_name,
                "project_slug": project.slug,
                "locale": "vi",
                "content_type": "faq",
                "source_owner": "admin",
            },
            project_id=project.id,
            mime_type="text/markdown",
            stage="PUBLISHED",
            digest_summary="FAQ managed from the project editor.",
            digest_meta={"source": "faq_editor"},
        )
        self.db.add(doc)
        await self.db.flush()
        return doc

    async def delete_faq_chunk(self, chunk_id: uuid.UUID) -> None:
        chunk = await self.db.get(KnowledgeChunk, chunk_id)
        if chunk:
            await self.db.delete(chunk)

    async def set_chunk_embedding(self, chunk_id: uuid.UUID, embedding: str) -> None:
        await self.db.execute(
            text(
                "UPDATE knowledge_chunks "
                "SET embedding = CAST(:embedding AS vector) "
                "WHERE id = :cid"
            ),
            {"cid": str(chunk_id), "embedding": embedding},
        )

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
