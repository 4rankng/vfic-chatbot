#!/usr/bin/env python3
"""Print a read-only plan for migrating legacy documents into KB releases.

This command deliberately has no apply mode. It selects only published,
project-scoped documents that are not already linked to a KB release, validates
that each target Project has an active KB version, and prints source checksums.
It never creates a KB version, writes a file, queues ingestion, or publishes.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.company import Project
from app.models.knowledge import (
    KBTextFile,
    KBVersion,
    KBVersionStatus,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.services.knowledge.legacy_document_migration import (
    LegacyDocumentMigrationCandidate,
    LegacyDocumentMigrationPlanError,
    build_legacy_document_migration_plan,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Required acknowledgement that this command only reads and reports.",
    )
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("--dry-run is required; this command has no apply mode")
    return args


def _legacy_document_query():
    return (
        select(KnowledgeDocument.id, KnowledgeDocument.project_id, KnowledgeDocument.raw_text)
        .outerjoin(KBTextFile, KBTextFile.document_id == KnowledgeDocument.id)
        .where(
            KnowledgeDocument.status == KnowledgeStatus.PUBLISHED,
            KBTextFile.id.is_(None),
        )
        .order_by(KnowledgeDocument.project_id, KnowledgeDocument.id)
    )


def _verified_active_version_query(project_ids: set):
    return (
        select(Project.id, KBVersion.id.label("active_kb_version_id"))
        .join(KBVersion, KBVersion.id == Project.active_kb_version_id)
        .where(
            Project.id.in_(project_ids),
            KBVersion.project_id == Project.id,
            KBVersion.status == KBVersionStatus.ACTIVE,
        )
    )


def _load_plan(session: Session):
    document_rows = session.execute(_legacy_document_query()).all()
    candidates = [
        LegacyDocumentMigrationCandidate(
            document_id=row.id,
            project_id=row.project_id,
            raw_text=row.raw_text,
        )
        for row in document_rows
    ]
    project_ids = {candidate.project_id for candidate in candidates if candidate.project_id is not None}
    project_rows = session.execute(_verified_active_version_query(project_ids)).all()
    active_kb_versions = {row.id: row.active_kb_version_id for row in project_rows}
    return build_legacy_document_migration_plan(
        candidates,
        active_kb_versions=active_kb_versions,
    )


def _serialize_plan(plan) -> dict[str, object]:
    return {
        "mode": "dry-run",
        "project_count": len(plan),
        "document_count": sum(len(item.source_documents) for item in plan),
        "projects": [
            {
                "project_id": str(item.project_id),
                "active_kb_version_id": str(item.active_kb_version_id),
                "documents": [
                    {"document_id": str(document_id), "source_sha256": source_sha256}
                    for document_id, source_sha256 in item.source_documents
                ],
            }
            for item in plan
        ],
    }


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    from sqlalchemy import create_engine

    engine = create_engine(
        get_settings().database_url_sync,
        execution_options={"isolation_level": "REPEATABLE READ"},
    )
    try:
        with Session(engine) as session:
            with session.begin():
                plan = _load_plan(session)
    except LegacyDocumentMigrationPlanError as exc:
        print(f"migration plan refused: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    print(json.dumps(_serialize_plan(plan), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
