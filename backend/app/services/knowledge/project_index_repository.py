"""Repository for the project catalog card (``projects.summary`` / ``index_card``)
and the structured bus-timetable rebuild."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.core.preamble_cache import NS_PREAMBLE


class ProjectIndexRepo:
    """Read/write the project catalog card (``projects.summary`` / ``index_card``)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_usable_corpus(self, project_id: uuid.UUID) -> list:
        """Usable-unit content+category, newest-first, capped at 200 (master-index input)."""
        return list((
            await self.db.execute(
                text(
                    "SELECT kc.content, kc.category FROM knowledge_chunks kc "
                    "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                    "JOIN projects p ON p.id = kd.project_id "
                    "WHERE kd.project_id = :pid "
                    "AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                    "AND kc.kb_version_id = p.active_kb_version_id "
                    "ORDER BY kc.created_at DESC LIMIT 200"
                ),
                {"pid": str(project_id)},
            )
        ).all())

    async def update_card(self, project_id: uuid.UUID, summary: str | None, card: dict) -> None:
        """Overwrite the project's summary + LLM-generated catalog card (JSONB)."""
        await self.db.execute(
            text(
                "UPDATE projects SET summary = :summary, index_card = CAST(:card AS jsonb) "
                "WHERE id = :pid"
            ),
            {
                "summary": summary,
                "card": json.dumps(card, ensure_ascii=False),
                "pid": str(project_id),
            },
        )
        await self.db.commit()
        await bump_cache_version(NS_PREAMBLE)

    async def sync_highlights(self, project_id: uuid.UUID, *, commit: bool = True) -> None:
        """Mirror the project's is_highlight feature values into ``index_card.highlights``.

        Feature-derived highlights are authoritative when present (override the LLM card).
        No-op when the project has no highlighted features.
        """
        rows = (
            await self.db.execute(
                text(
                    "SELECT value_text FROM job_feature_values "
                    "WHERE project_id = :pid AND is_highlight "
                    "ORDER BY display_priority ASC, strength_score DESC LIMIT 6"
                ),
                {"pid": str(project_id)},
            )
        ).all()
        if not rows:
            return
        await self.db.execute(
            text(
                "UPDATE projects SET index_card = "
                "jsonb_set(COALESCE(index_card, '{}'::jsonb), '{highlights}', CAST(:hl AS jsonb)) "
                "WHERE id = :pid"
            ),
            {
                "hl": json.dumps([r.value_text for r in rows], ensure_ascii=False),
                "pid": str(project_id),
            },
        )
        if commit:
            await self.db.commit()
            await bump_cache_version(NS_PREAMBLE)


async def rebuild_bus_timetable(db: AsyncSession) -> tuple[int, int]:
    """Rebuild the structured bus-timetable graph from the parsed ``LGDisplay`` document.

    Reads the legacy ``LGDisplay.txt`` raw text, parses it in pure Python
    (``app.services.knowledge.bus_timetable``), and persists via
    ``BusTimetableRepo``. Behaviour-identical to the former
    ``rebuild_bus_timetable_from_documents()`` SQL function (golden-gated). Best-effort:
    callers wrap in ``try/except``; returns ``(0, 0)`` when no source document is present
    (matches the SQL fn's empty loop — does NOT scan unrelated documents).
    """
    # Lazy import keeps this data-access module free of a load-time dependency on the
    # parser package.
    from app.services.knowledge.bus_timetable import parse_bus_timetable
    from app.services.knowledge.bus_timetable.repository import BusTimetableRepo

    source = (
        (
            await db.execute(
                text(
                    "SELECT kd.raw_text, p.slug AS project_slug "
                    "FROM knowledge_documents kd "
                    "JOIN projects p ON p.id = kd.project_id "
                    "JOIN kb_text_files ktf ON ktf.document_id = kd.id "
                    "JOIN kb_versions kv ON kv.id = p.active_kb_version_id "
                    "WHERE kd.file_name = :fn "
                    "  AND kd.status NOT IN ('ARCHIVED', 'FAILED') "
                    "  AND kd.raw_text IS NOT NULL "
                    "  AND ktf.kb_version_id = p.active_kb_version_id "
                    "  AND kv.status = 'ACTIVE' "
                    "ORDER BY kd.updated_at DESC, kd.created_at DESC "
                    "LIMIT 1"
                ),
                {"fn": "LGDisplay.txt"},
            )
        )
        .mappings()
        .first()
    )
    if source is None:
        return (0, 0)
    parsed = parse_bus_timetable(source["raw_text"])
    return await BusTimetableRepo(db).upsert(
        parsed,
        project_slug=source["project_slug"],
        company_name="LG Display",
        source_name="LGDisplay.txt",
    )
