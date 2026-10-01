"""Repository for the ``knowledge_documents`` table + ingest crash handlers."""

from __future__ import annotations

from typing import cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession


class KnowledgeDocumentRepo:
    """Data access for ``knowledge_documents`` table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def delete_orphans_by_drive_ids(self, current_drive_ids: list[str]) -> int:
        """Drop documents whose drive_file_id is no longer in Drive (cascades chunks)."""
        res = await self.db.execute(
            text(
                "DELETE FROM knowledge_documents WHERE drive_file_id IS NOT NULL "
                "AND drive_file_id <> ALL(CAST(:ids AS text[]))"
            ),
            {"ids": current_drive_ids},
        )
        await self.db.commit()
        return cast(CursorResult, res).rowcount or 0


def mark_document_failed_sync(database_url: str, doc_id: str, error: str, *, processing_token=None) -> None:
    """Record outer worker crashes only for the exact training claimant."""
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models.knowledge import KnowledgeDocument, KnowledgeStatus

    engine = create_engine(database_url, future=True)
    try:
        with Session(engine) as session, session.begin():
            doc = session.scalar(select(KnowledgeDocument).where(
                KnowledgeDocument.id == uuid.UUID(doc_id)
            ).with_for_update())
            if doc is None:
                return
            if doc.status == KnowledgeStatus.ARCHIVED:
                return
            training = (doc.metadata_ or {}).get("project_training")
            if training is not None:
                if training.get("processing_token") != str(processing_token):
                    return
                doc.metadata_ = {**(doc.metadata_ or {}), "project_training": {
                    **training, "processing_token": None, "lease_expires_at": None,
                }}
                progress = (doc.digest_meta or {}).get("project_training", {})
                doc.digest_meta = {**(doc.digest_meta or {}), "project_training": {
                    **progress, "status": "FAILED", "error": error[:1000],
                }}
            doc.status = KnowledgeStatus.FAILED
            doc.stage = "FAILED"
            doc.error = error[:1000]
            doc.updated_at = datetime.now(UTC)
    finally:
        engine.dispose()


def mark_version_failed_sync(database_url: str, version_id: str, error: str) -> None:
    """Sync fallback to mark a KB version as FAILED after an RQ crash."""
    from sqlalchemy import create_engine

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE kb_versions "
                    "SET status = 'FAILED', error_message = :error "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": version_id, "error": error[:1000]},
            )
    finally:
        engine.dispose()


def mark_category_revision_failed_sync(
    database_url: str,
    revision_id: str,
    processing_token: str,
    failure_code: str,
) -> None:
    """Fence an outer RQ failure to the exact category processing attempt."""
    from sqlalchemy import create_engine

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE knowledge_category_revisions "
                    "SET status = 'FAILED', failure_code = :failure_code, "
                    "error_message = 'Category worker failed', processing_token = NULL, "
                    "processing_started_at = NULL, lease_expires_at = NULL "
                        "WHERE id = CAST(:id AS uuid) AND ("
                        "(status = 'STAGED' AND processing_token IS NULL) OR "
                        "(status = 'PROCESSING' "
                        "AND processing_token = CAST(:processing_token AS uuid)))"
                ),
                {
                    "id": revision_id,
                    "processing_token": processing_token,
                    "failure_code": failure_code,
                },
            )
    finally:
        engine.dispose()
