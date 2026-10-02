"""Project data access — all raw SQL + ORM lookup queries live here.

The service layer delegates to :class:`ProjectRepository` for anything that touches
``text()`` or low-level ORM select, keeping business logic in the service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company, Project
from app.models.knowledge import (
    KBTextFile,
    KBVersion,
    KBVersionStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.shared.domain.errors import NotFoundError
from app.services.knowledge.text_ingestion import kb_text_stats


class ProjectRepository:
    """Encapsulates raw SQL + ORM lookups used by :class:`ProjectService`."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def knowledge_document_counts(self, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Count each project's on-record source documents ("Tài liệu").

        Three families count, one row each: the files of the active KB version
        (``kb_text_files``), the single-page direct file, and uploaded source
        documents (``knowledge_documents``, brief uploads included) that no other
        family already represents. Managed ``knowledge_documents`` rows are
        excluded so a document is counted exactly once: ``kb_version`` documents
        through their ``kb_text_files`` row, ``direct_context`` through
        ``knowledge_base_direct_files``, and ``category_markdown`` / ``faq_editor`` rows — internal artifacts of the
        category and FAQ writers — at all.
        """
        if not project_ids:
            return {}
        rows = (
            await self.db.execute(
                text(
                    "SELECT p.id AS project_id, "
                    "count(DISTINCT ktf.id) + count(DISTINCT kbdf.id) + count(DISTINCT kd.id) "
                    "AS file_count "
                    "FROM projects p "
                    "LEFT JOIN kb_text_files ktf ON ktf.kb_version_id = p.active_kb_version_id "
                    "LEFT JOIN knowledge_base_direct_files kbdf "
                    "ON kbdf.knowledge_base_id = p.knowledge_base_id "
                    "LEFT JOIN knowledge_documents kd ON kd.project_id = p.id "
                    "AND kd.status::text <> 'ARCHIVED' "
                    "AND kd.source NOT IN "
                    "('kb_version', 'category_markdown', 'faq_editor', 'direct_context') "
                    "WHERE p.id = ANY(CAST(:ids AS uuid[])) "
                    "GROUP BY p.id"
                ),
                {"ids": [str(pid) for pid in project_ids]},
            )
        ).all()
        return {row.project_id: int(row.file_count) for row in rows if row.project_id is not None}

    async def count_bus_routes(self, project_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    text(
                        "SELECT count(*) FROM bus_routes br "
                        "JOIN projects p ON p.id = br.project_id "
                        "WHERE br.project_id = :pid AND ("
                        "(p.category_authority_started "
                        "AND br.source_category_revision_id IS NOT NULL) OR "
                        "(NOT p.category_authority_started "
                        "AND br.source_category_revision_id IS NULL))"
                    ),
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
                        "SELECT br.id, br.route_name, br.route_no, br.route_variant, "
                        "       br.shift, br.direction, br.area, br.mode, "
                        "       br.source_page, br.notes "
                        "FROM bus_routes br JOIN projects p ON p.id = br.project_id "
                        "WHERE br.project_id = :pid AND ("
                        "  (p.category_authority_started "
                        "   AND br.source_category_revision_id IS NOT NULL) OR "
                        "  (NOT p.category_authority_started "
                        "   AND br.source_category_revision_id IS NULL)"
                        ") "
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
                        "       kc.required_terms, kc.forbidden_terms, "
                        "       kc.metadata ->> 'source_anchor' AS source_anchor, "
                        "       COALESCE(ktf.filename, kd.file_name) AS file_name "
                        "FROM knowledge_chunks kc "
                        "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                        "JOIN projects p ON p.id = kd.project_id "
                        "LEFT JOIN knowledge_categories cat "
                        "  ON cat.project_id = p.id AND cat.category_key = 'faq' "
                        "LEFT JOIN kb_text_files ktf ON ktf.id = kc.file_id "
                        "WHERE kd.project_id = :pid "
                        "  AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                        "  AND ((p.category_authority_started "
                        "        AND kc.category_revision_id = cat.active_revision_id) "
                        "       OR (NOT p.category_authority_started "
                        "           AND kc.kb_version_id = p.active_kb_version_id)) "
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
                        "       kc.required_terms, kc.forbidden_terms, "
                        "       kc.metadata ->> 'source_anchor' AS source_anchor, "
                        "       COALESCE(ktf.filename, kd.file_name) AS file_name "
                        "FROM knowledge_chunks kc "
                        "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                        "JOIN projects p ON p.id = kd.project_id "
                        "LEFT JOIN knowledge_categories cat "
                        "  ON cat.project_id = p.id AND cat.category_key = 'faq' "
                        "LEFT JOIN kb_text_files ktf ON ktf.id = kc.file_id "
                        "WHERE kd.project_id = :pid "
                        "  AND kc.id = :cid "
                        "  AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                        "  AND ((p.category_authority_started "
                        "        AND kc.category_revision_id = cat.active_revision_id) "
                        "       OR (NOT p.category_authority_started "
                        "           AND kc.kb_version_id = p.active_kb_version_id)) "
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

    async def ensure_active_faq_file(
        self, project: Project, document: KnowledgeDocument
    ) -> KBTextFile:
        version = None
        if project.active_kb_version_id is not None:
            version = await self.db.get(KBVersion, project.active_kb_version_id)
        if version is None:
            version = (
                await self.db.scalars(
                    select(KBVersion)
                    .where(
                        KBVersion.project_id == project.id,
                        KBVersion.status == KBVersionStatus.ACTIVE,
                    )
                    .order_by(KBVersion.version_no.desc())
                    .limit(1)
                )
            ).first()
            if version is not None:
                project.active_kb_version_id = version.id
        if version is None:
            next_version = int(
                await self.db.scalar(
                    select(func.coalesce(func.max(KBVersion.version_no), 0) + 1).where(
                        KBVersion.project_id == project.id
                    )
                )
                or 1
            )
            version = KBVersion(
                project_id=project.id,
                version_no=next_version,
                status=KBVersionStatus.ACTIVE,
                published_at=datetime.now(UTC),
            )
            self.db.add(version)
            await self.db.flush()
            project.active_kb_version_id = version.id
        raw_text = document.raw_text or ""
        stats = kb_text_stats(raw_text)
        text_file = (
            await self.db.scalars(
                select(KBTextFile)
                .where(KBTextFile.document_id == document.id)
                .order_by(KBTextFile.created_at.asc())
                .limit(1)
            )
        ).first()
        if text_file is None:
            text_file = KBTextFile(
                project_id=project.id,
                kb_version_id=version.id,
                document_id=document.id,
                filename=document.file_name,
                mime_type=document.mime_type or "text/markdown",
                raw_text=raw_text,
                normalized_text=stats.normalized_text,
                content_sha256=stats.content_sha256,
                char_count=stats.char_count,
                line_count=stats.line_count,
            )
            self.db.add(text_file)
        else:
            text_file.project_id = project.id
            text_file.kb_version_id = version.id
            text_file.filename = document.file_name
            text_file.mime_type = document.mime_type or "text/markdown"
            text_file.raw_text = raw_text
            text_file.normalized_text = stats.normalized_text
            text_file.content_sha256 = stats.content_sha256
            text_file.char_count = stats.char_count
            text_file.line_count = stats.line_count
        await self.db.flush()
        return text_file

    async def delete_faq_chunk(self, chunk_id: uuid.UUID) -> None:
        chunk = await self.db.get(KnowledgeChunk, chunk_id)
        if chunk:
            await self.db.delete(chunk)

    async def set_chunk_embedding(self, chunk_id: uuid.UUID, embedding: str) -> None:
        await self.db.execute(
            text(
                "UPDATE knowledge_chunks SET embedding = CAST(:embedding AS vector) WHERE id = :cid"
            ),
            {"cid": str(chunk_id), "embedding": embedding},
        )

    async def set_chunk_search_text(self, chunk_id: uuid.UUID, search_text: str) -> None:
        """Override a FAQ chunk's ``search_text`` directly.

        The ``knowledge_chunks_search_text`` trigger (migration 0014) rewrites
        ``search_text`` from ``content || source_quote || summary`` on any
        INSERT/UPDATE that touches those columns — so an ORM assignment is
        clobbered and FAQ question-variants never reach the trigram index. This
        issues a column-scoped UPDATE (content/source_quote/summary untouched) so
        the trigger does not fire and the variants-augmented text persists.
        """
        await self.db.execute(
            text("UPDATE knowledge_chunks SET search_text = :t WHERE id = :cid"),
            {"cid": str(chunk_id), "t": search_text},
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
        """The document feature extraction reads.

        The legacy KB-version lane joins the active version's text file; the
        training/category lane stores the source brief as a plain upload with
        ``raw_text`` and no KB-version join, so fall back to the latest such
        document (OPS note: without this, feature extraction refused every
        category-lane project with "no source document with text").
        """
        legacy = (
            await self.db.scalars(
                select(KnowledgeDocument)
                .join(KBTextFile, KBTextFile.document_id == KnowledgeDocument.id)
                .join(Project, Project.active_kb_version_id == KBTextFile.kb_version_id)
                .where(
                    KnowledgeDocument.project_id == project_id,
                    KnowledgeDocument.raw_text.is_not(None),
                    Project.id == project_id,
                )
                .order_by(KnowledgeDocument.created_at.desc())
                .limit(1)
            )
        ).first()
        if legacy is not None:
            return legacy
        return (
            await self.db.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.project_id == project_id,
                    KnowledgeDocument.raw_text.is_not(None),
                    KnowledgeDocument.raw_text != "",
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
