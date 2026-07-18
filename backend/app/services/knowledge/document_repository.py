"""Repository for the ``knowledge_documents`` table + ingest crash handlers."""

from __future__ import annotations

from sqlalchemy import text
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
        return res.rowcount or 0


def mark_document_failed_sync(database_url: str, doc_id: str, error: str) -> None:
    """Sync fallback to mark a knowledge document as FAILED.

    Used by the ingest worker's crash handler (``run_ingest_job``) when RQ's
    death penalty raises an exception *outside* the asyncio.run() frame, making
    the async session unavailable. Creates a short-lived sync engine; callers
    must ensure ``database_url`` is the synchronous (psycopg) URL.
    """
    from sqlalchemy import create_engine

    try:
        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE knowledge_documents "
                        "SET status = 'FAILED', stage = 'FAILED', "
                        "error = :error, updated_at = now() "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": doc_id, "error": error[:1000]},
                )
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 — do not mask the original RQ failure
        raise


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
