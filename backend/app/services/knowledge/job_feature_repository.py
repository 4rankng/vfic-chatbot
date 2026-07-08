"""Repository for the ``job_feature_values`` + ``worker_feature_catalog`` tables."""

from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_FEATURE_COLUMNS = (
    "jfv.id, jfv.project_id, jfv.feature_id, jfv.value_text, jfv.value_json, "
    "jfv.strength_score, jfv.display_priority, jfv.is_highlight, jfv.is_missing, "
    "jfv.needs_clarification, jfv.evidence_text, jfv.source_document_id, jfv.updated_at, "
    "wfc.feature_key, wfc.name_vi, wfc.category, wfc.worker_question_vi"
)
_FEATURE_FROM = "job_feature_values jfv JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id"


class JobFeatureValueRepo:
    """Read/write the ``job_feature_values`` + ``worker_feature_catalog`` tables."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def fetch_catalog(self) -> list:
        """Return the active catalog ordered by importance then key.

        Drives both the extraction prompt and the one-row-per-feature write, so inactive
        criteria (migration 0009) drop out of extraction entirely.
        """
        return (
            await self.db.execute(
                text(
                    "SELECT id, feature_key, name_vi, worker_question_vi, default_importance_score "
                    "FROM worker_feature_catalog WHERE is_active = true "
                    "ORDER BY default_importance_score DESC, feature_key"
                )
            )
        ).all()

    async def active_catalog_size(self) -> int:
        """Count of active catalog features — the readiness denominator.

        Derived rather than hardcoded so reactivating a criterion stays consistent with the
        extraction prompt and list query without a code edit.
        """
        return int(
            (
                await self.db.execute(
                    text("SELECT count(*) FROM worker_feature_catalog WHERE is_active = true")
                )
            ).scalar()
            or 0
        )

    async def ensure_active_rows_for_project(self, project_id: uuid.UUID) -> None:
        """Backfill missing active feature rows for projects extracted before catalog changes."""
        await self.db.execute(
            text(
                """
                INSERT INTO job_feature_values
                  (project_id, feature_id, value_text, value_json, strength_score, display_priority,
                   is_highlight, is_missing, needs_clarification, evidence_text)
                SELECT
                  CAST(:pid AS uuid),
                  wfc.id,
                  '',
                  '{}'::jsonb,
                  wfc.default_importance_score,
                  row_number() OVER (
                    ORDER BY wfc.default_importance_score DESC, wfc.feature_key
                  ) - 1,
                  false,
                  true,
                  false,
                  'Chưa có thông tin trong nguồn đã tải lên.'
                FROM worker_feature_catalog wfc
                WHERE wfc.is_active = true
                  AND NOT EXISTS (
                    SELECT 1
                    FROM job_feature_values jfv
                    WHERE jfv.project_id = CAST(:pid AS uuid)
                      AND jfv.feature_id = wfc.id
                  )
                ON CONFLICT (project_id, feature_id) DO NOTHING
                """
            ),
            {"pid": str(project_id)},
        )
        await self.db.commit()

    async def replace_for_project(
        self,
        project_id: uuid.UUID,
        doc_id: uuid.UUID,
        rows: list[tuple[Any, dict]],
    ) -> None:
        """Overwrite a project's feature values (delete-then-insert, one row per catalog feature).

        ``rows`` is a list of ``(catalog_row, coerced_feature_dict)`` in display order; the
        enumerate index becomes ``display_priority``.
        """
        await self.db.execute(
            text("DELETE FROM job_feature_values WHERE project_id = :pid"),
            {"pid": str(project_id)},
        )
        if rows:
            params_list = [
                {
                    "pid": str(project_id),
                    "fid": str(c.id),
                    "vtext": coerced["value_text"],
                    "vjson": json.dumps(coerced["value_json"], ensure_ascii=False),
                    "strength": coerced["strength_score"],
                    "prio": priority,
                    "hl": coerced["is_highlight"],
                    "missing": coerced["is_missing"],
                    "clarify": coerced["needs_clarification"],
                    "evidence": coerced["evidence_text"],
                    "did": str(doc_id),
                }
                for priority, (c, coerced) in enumerate(rows)
            ]
            await self.db.execute(
                text(
                    "INSERT INTO job_feature_values "
                    "(project_id, feature_id, value_text, value_json, strength_score, display_priority, "
                    " is_highlight, is_missing, needs_clarification, evidence_text, source_document_id) "
                    "VALUES (CAST(:pid AS uuid), CAST(:fid AS uuid), :vtext, CAST(:vjson AS jsonb), "
                    "        :strength, :prio, :hl, :missing, :clarify, :evidence, CAST(:did AS uuid))"
                ),
                params_list,
            )
        await self.db.commit()

    async def merge_for_project(
        self,
        project_id: uuid.UUID,
        doc_id: uuid.UUID,
        rows: list[tuple[Any, dict]],
    ) -> None:
        """Merge extracted feature values into a project's read model.

        New uploads supplement the existing project profile. A concrete value from the
        new document updates the row (newer posting wins for obsolete details), while a
        missing/unclear extraction only inserts a gap row when the project has no value
        yet; it never erases an older useful answer.
        """
        if rows:
            params_list = [
                {
                    "pid": str(project_id),
                    "fid": str(c.id),
                    "vtext": coerced["value_text"],
                    "vjson": json.dumps(coerced["value_json"], ensure_ascii=False),
                    "strength": coerced["strength_score"],
                    "prio": priority,
                    "hl": coerced["is_highlight"],
                    "missing": coerced["is_missing"],
                    "clarify": coerced["needs_clarification"],
                    "evidence": coerced["evidence_text"],
                    "did": str(doc_id),
                }
                for priority, (c, coerced) in enumerate(rows)
            ]
            await self.db.execute(
                text(
                    "INSERT INTO job_feature_values "
                    "(project_id, feature_id, value_text, value_json, strength_score, display_priority, "
                    " is_highlight, is_missing, needs_clarification, evidence_text, source_document_id) "
                    "VALUES (CAST(:pid AS uuid), CAST(:fid AS uuid), :vtext, CAST(:vjson AS jsonb), "
                    "        :strength, :prio, :hl, :missing, :clarify, :evidence, CAST(:did AS uuid)) "
                    "ON CONFLICT (project_id, feature_id) DO UPDATE SET "
                    "  value_text = EXCLUDED.value_text, "
                    "  value_json = EXCLUDED.value_json, "
                    "  strength_score = EXCLUDED.strength_score, "
                    "  display_priority = EXCLUDED.display_priority, "
                    "  is_highlight = EXCLUDED.is_highlight, "
                    "  is_missing = EXCLUDED.is_missing, "
                    "  needs_clarification = EXCLUDED.needs_clarification, "
                    "  evidence_text = EXCLUDED.evidence_text, "
                    "  source_document_id = EXCLUDED.source_document_id "
                    "WHERE COALESCE(EXCLUDED.is_missing, false) = false "
                    "  AND COALESCE(EXCLUDED.needs_clarification, false) = false "
                    "  AND btrim(EXCLUDED.value_text) <> ''"
                ),
                params_list,
            )
        await self.db.commit()

    async def list_for_project(self, project_id: uuid.UUID) -> list:
        """A project's feature values joined to the catalog (catalog display order)."""
        await self.ensure_active_rows_for_project(project_id)
        return (
            await self.db.execute(
                text(
                    f"SELECT {_FEATURE_COLUMNS} FROM {_FEATURE_FROM} "  # noqa: S608 — static f-string
                    "WHERE jfv.project_id = :pid "
                    "  AND wfc.is_active = true "
                    "ORDER BY jfv.display_priority ASC, wfc.default_importance_score DESC"
                ),
                {"pid": str(project_id)},
            )
        ).all()

    async def exists_for_project(self, feature_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """True if the feature value belongs to the project."""
        return (
            await self.db.execute(
                text("SELECT 1 FROM job_feature_values WHERE id = :fid AND project_id = :pid"),
                {"fid": str(feature_id), "pid": str(project_id)},
            )
        ).first() is not None

    async def readiness_by_project(self, project_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Batched ready-feature count per project.

        Ready = a value row exists, is not missing/unclear, and has non-empty
        ``value_text``. One batched query (``= ANY(:ids)``); projects with no
        ready features are simply absent from the dict (caller treats missing
        as 0). Uses the same text/param style as :meth:`list_for_project`.
        """
        if not project_ids:
            return {}
        rows = (
            await self.db.execute(
                text(
                    "SELECT jfv.project_id, COUNT(*) AS ready "
                    "FROM job_feature_values jfv "
                    "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                    "WHERE jfv.project_id = ANY(:ids) "
                    "  AND wfc.is_active = true "
                    "  AND COALESCE(jfv.is_missing, false) = false "
                    "  AND COALESCE(jfv.needs_clarification, false) = false "
                    "  AND jfv.value_text IS NOT NULL "
                    "  AND btrim(jfv.value_text) <> '' "
                    "GROUP BY jfv.project_id"
                ),
                {"ids": [str(pid) for pid in project_ids]},
            )
        ).all()
        return {r.project_id: int(r.ready) for r in rows}

    async def update_fields(self, assignments: list[str], params: dict) -> None:
        """Apply a dynamically-built SET clause (admin feature edit). No-op if no assignments."""
        if not assignments:
            return
        await self.db.execute(
            text(f"UPDATE job_feature_values SET {', '.join(assignments)} WHERE id = :fid"),  # noqa: S608 — built from a fixed field whitelist in the service
            params,
        )

    async def get(self, feature_id: uuid.UUID):
        """One feature value joined to the catalog, or None."""
        return (
            await self.db.execute(
                text(f"SELECT {_FEATURE_COLUMNS} FROM {_FEATURE_FROM} WHERE jfv.id = :fid"),  # noqa: S608 — static f-string
                {"fid": str(feature_id)},
            )
        ).first()
