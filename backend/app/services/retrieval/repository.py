"""Retrieval data-access for the agent layer.

Verbatim ports of the queries that ``app/graph/tools.py`` and
``app/graph/context.py`` previously ran inline, so the graph layer no longer owns
``text()`` SQL. Behaviour is unchanged: the tools now format the rows this repo
returns.

NO business logic, NO LLM/embedder calls — callers compute the embedding (a
graph-layer concern) and hand the repo a vector literal. Methods return SQLAlchemy
Row lists/scalars exactly as the inline ``db.execute(...).all()`` calls did.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RetrievalRepository:
    """Read-only retrieval queries backing the agent's tools + prompt assembly."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def match_memories(self, emb: str, top_k: int, filter_json: str) -> list:
        """Top-k memory rows for a chat (``match_memories`` SQL function)."""
        return (
            await self.db.execute(
                text(
                    "SELECT content, similarity FROM match_memories("
                    "CAST(:emb AS vector), :k, CAST(:filter AS jsonb))"
                ),
                {"emb": emb, "k": top_k, "filter": filter_json},
            )
        ).all()

    async def match_documents(
        self, emb: str, top_k: int, filter_json: str, *, project_ids: list[str] | None = None
    ) -> list:
        """Top-k usable knowledge rows directly from chunks + documents.

        The old path called the ``documents`` compatibility view. Migration 0010 removes
        that view, so the app now owns the explicit query and returns namespaced
        metadata for citations/effective-date handling.
        """
        project_clause = ""
        params: dict[str, object] = {"emb": emb, "k": top_k, "filter": filter_json}
        if project_ids:
            project_clause = "AND d.project_id = ANY(CAST(:pids AS uuid[]))"
            params["pids"] = project_ids
        return (
            await self.db.execute(
                text(
                    "SELECT c.id, c.content, c.metadata, "
                    "       1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity "
                    "FROM knowledge_chunks c "
                    "JOIN knowledge_documents d ON d.id = c.document_id "
                    "WHERE d.status NOT IN ('ARCHIVED', 'FAILED') "
                    "  AND c.embedding IS NOT NULL "
                    "  AND (CAST(:filter AS jsonb) = '{}'::jsonb OR c.metadata @> CAST(:filter AS jsonb)) "
                    f"  {project_clause} "  # noqa: S608 - clause is fixed above
                    "  AND ("
                    "    c.metadata #>> '{document_metadata,schema_version}' IS NULL "
                    "    OR ("
                    "      COALESCE(c.metadata #>> '{document_metadata,effective_from}', '0001-01-01')::date <= CURRENT_DATE "
                    "      AND (c.metadata #>> '{document_metadata,effective_to}' IS NULL "
                    "           OR (c.metadata #>> '{document_metadata,effective_to}')::date >= CURRENT_DATE)"
                    "    )"
                    "  ) "
                    "ORDER BY c.embedding <=> CAST(:emb AS vector) "
                    "LIMIT :k"
                ),
                params,
            )
        ).all()

    async def project_id_by_slug(self, slug: str, *, active_only: bool = False) -> uuid.UUID | None:
        """Resolve a project id from its (unique) slug; optionally require ``is_active``."""
        sql = "SELECT id FROM projects WHERE slug = :s"
        if active_only:
            sql += " AND is_active"
        return (await self.db.execute(text(sql), {"s": slug})).scalar_one_or_none()

    async def list_active_projects(self) -> list:
        """name/slug/summary of active projects (catalog tool)."""
        return (
            await self.db.execute(
                text("SELECT name, slug, summary FROM projects WHERE is_active ORDER BY name")
            )
        ).all()

    async def active_projects_with_card(self) -> list:
        """name/slug/summary/index_card of active projects (master-index prompt block)."""
        return (
            await self.db.execute(
                text(
                    "SELECT name, slug, summary, index_card FROM projects WHERE is_active ORDER BY name"
                )
            )
        ).all()

    async def active_persona_body(self) -> str | None:
        """``body_md`` of the single active global persona, or None."""
        return (
            await self.db.execute(
                text("SELECT body_md FROM personas WHERE is_active AND project_id IS NULL LIMIT 1")
            )
        ).scalar_one_or_none()

    async def search_bus_timetable(self, company: str, question: str, limit: int) -> list:
        """Rows from the ``search_bus_timetable`` SQL fn (one row per stop)."""
        return (
            await self.db.execute(
                text(
                    "SELECT * FROM search_bus_timetable('vfic', :company, :question, NULL, NULL, :limit)"
                ),
                {"company": company, "question": question, "limit": limit},
            )
        ).all()

    async def job_features_for_project(self, project_id: uuid.UUID) -> list:
        """A project's active worker features in catalog display order.

        Filtered to ``is_active`` catalog rows so disabled criteria (migration 0009) are
        hidden from the agent tool and readiness gauge without re-extraction.
        """
        return (
            await self.db.execute(
                text(
                    "SELECT jfv.value_text, jfv.value_json, jfv.is_highlight, jfv.is_missing, "
                    "       jfv.needs_clarification, jfv.evidence_text, "
                    "       wfc.name_vi, wfc.feature_key "
                    "FROM job_feature_values jfv "
                    "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                    "WHERE jfv.project_id = :pid AND wfc.is_active = true "
                    "ORDER BY jfv.display_priority ASC, wfc.default_importance_score DESC"
                ),
                {"pid": str(project_id)},
            )
        ).all()


__all__ = ["RetrievalRepository"]
