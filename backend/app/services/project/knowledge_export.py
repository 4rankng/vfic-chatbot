"""Export only a project's current, owned knowledge sources in one DB snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
import uuid

from sqlalchemy import and_, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Project
from app.models.knowledge import (
    KBTextFile,
    KBVersion,
    KBVersionStatus,
    KnowledgeBase,
    KnowledgeBaseDirectFile,
    KnowledgeBaseMode,
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.project_knowledge.domain.category_catalog import CATEGORY_DEFINITIONS
from app.project_knowledge.domain.legacy_job_references import strip_legacy_job_reference_source
from app.shared.domain.errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class ProjectKnowledgeExport:
    filename: str
    content: str


def _export_filename(slug: str, project_id: uuid.UUID) -> str:
    ascii_slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode()
    safe_slug = re.sub(r"[^a-z0-9_-]+", "-", ascii_slug.lower())[:80].strip("-_")
    return f"kb-{safe_slug or project_id.hex[:12]}.md"


def _heading(value: str) -> str:
    return " ".join(value.split())


async def export_project_knowledge(
    db: AsyncSession, project_id: uuid.UUID
) -> ProjectKnowledgeExport:
    """Read authority pointers, lifecycle, ownership and text in one statement.

    Publication/cutover commits the pointer and its sources atomically. One
    statement therefore sees either complete snapshot, including when the
    session has a previously loaded Project in its identity map. No ORM entity
    or metadata is serialized into the export.
    """
    owned_base = and_(
        KnowledgeBase.id == Project.knowledge_base_id,
        # Migrated/standalone bases may have no reverse owner yet. The
        # project's declared FK is authoritative in that case; an explicit
        # different owner must never be treated as this project's source.
        or_(KnowledgeBase.project_id.is_(None), KnowledgeBase.project_id == Project.id),
    )
    direct = (
        select(
            Project.id.label("project_id"),
            literal("direct").label("kind"),
            literal("").label("source_key"),
            KnowledgeBaseDirectFile.filename.label("source_title"),
            KnowledgeBaseDirectFile.raw_text.label("source_text"),
            KnowledgeBaseDirectFile.created_at.label("source_created_at"),
            KnowledgeBaseDirectFile.id.label("source_id"),
        )
        .select_from(Project)
        .join(KnowledgeBase, owned_base)
        .join(
            KnowledgeBaseDirectFile, KnowledgeBaseDirectFile.knowledge_base_id == KnowledgeBase.id
        )
        .where(Project.id == project_id, KnowledgeBase.mode == KnowledgeBaseMode.DIRECT_CONTEXT)
    )
    category = (
        select(
            Project.id.label("project_id"),
            literal("category").label("kind"),
            KnowledgeCategory.category_key.label("source_key"),
            KnowledgeCategoryRevision.source_filename.label("source_title"),
            KnowledgeCategoryRevision.source_markdown.label("source_text"),
            KnowledgeCategoryRevision.created_at.label("source_created_at"),
            KnowledgeCategoryRevision.id.label("source_id"),
        )
        .select_from(Project)
        .join(KnowledgeBase, owned_base)
        .join(KnowledgeCategory, KnowledgeCategory.project_id == Project.id)
        .join(
            KnowledgeCategoryRevision,
            and_(
                KnowledgeCategoryRevision.id == KnowledgeCategory.active_revision_id,
                KnowledgeCategoryRevision.category_id == KnowledgeCategory.id,
                KnowledgeCategoryRevision.status == KnowledgeCategoryRevisionStatus.ACTIVE,
            ),
        )
        .join(
            KnowledgeDocument,
            and_(
                KnowledgeDocument.category_revision_id == KnowledgeCategoryRevision.id,
                KnowledgeDocument.project_id == Project.id,
                KnowledgeDocument.status == KnowledgeStatus.PUBLISHED,
            ),
        )
        .where(
            Project.id == project_id,
            KnowledgeBase.mode == KnowledgeBaseMode.RAG,
            Project.category_authority_started.is_(True),
        )
    )
    legacy = (
        select(
            Project.id.label("project_id"),
            literal("legacy").label("kind"),
            literal("").label("source_key"),
            KBTextFile.filename.label("source_title"),
            KBTextFile.normalized_text.label("source_text"),
            KBTextFile.created_at.label("source_created_at"),
            KBTextFile.id.label("source_id"),
        )
        .select_from(Project)
        .join(KnowledgeBase, owned_base)
        .join(
            KBVersion,
            and_(
                KBVersion.id == Project.active_kb_version_id,
                KBVersion.project_id == Project.id,
                KBVersion.status == KBVersionStatus.ACTIVE,
            ),
        )
        .join(
            KBTextFile,
            and_(
                KBTextFile.kb_version_id == KBVersion.id,
                KBTextFile.project_id == Project.id,
            ),
        )
        .join(
            KnowledgeDocument,
            and_(
                KnowledgeDocument.id == KBTextFile.document_id,
                KnowledgeDocument.project_id == Project.id,
                KnowledgeDocument.category_revision_id.is_(None),
                KnowledgeDocument.status == KnowledgeStatus.PUBLISHED,
            ),
        )
        .where(
            Project.id == project_id,
            KnowledgeBase.mode == KnowledgeBaseMode.RAG,
            Project.category_authority_started.is_(False),
        )
    )
    sources = union_all(direct, category, legacy).subquery()
    result = await db.execute(
        select(
            Project.name.label("project_name"),
            Project.slug.label("project_slug"),
            sources.c.kind,
            sources.c.source_key,
            sources.c.source_title,
            sources.c.source_text,
            sources.c.source_created_at,
            sources.c.source_id,
        )
        .select_from(Project)
        .outerjoin(sources, sources.c.project_id == Project.id)
        .where(Project.id == project_id)
    )
    rows = result.mappings().all()
    if not rows:
        raise NotFoundError("Project not found")
    saved_sources = []
    for row in rows:
        source_text = strip_legacy_job_reference_source(row["source_text"] or "")
        if source_text.strip():
            saved_sources.append({**row, "source_text": source_text})
    if not saved_sources:
        raise ConflictError("Dự án chưa có kiến thức đang sử dụng để xuất.")

    category_order = {item.key: index for index, item in enumerate(CATEGORY_DEFINITIONS)}
    category_labels = {item.key: item.label_vi for item in CATEGORY_DEFINITIONS}
    saved_sources.sort(
        key=lambda row: (
            category_order.get(row["source_key"], len(category_order)),
            row["source_created_at"],
            str(row["source_id"]),
        )
    )
    sections = [f"# Kiến thức dự án: {_heading(rows[0]['project_name'])}\n\n"]
    for source in saved_sources:
        title = (
            category_labels.get(source["source_key"]) or source["source_title"]
            if source["kind"] == "category"
            else source["source_title"]
        )
        # Retain factual text and whitespace after retiring legacy reference fields.
        sections.append(f"## {_heading(title)}\n\n{source['source_text']}\n\n")
    return ProjectKnowledgeExport(
        filename=_export_filename(rows[0]["project_slug"], project_id),
        content="".join(sections),
    )
