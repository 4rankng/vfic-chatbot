"""Feature publication shared by whole-brief batches and legacy cutover.

Category snapshots fence deferred source features without importing the category
lifecycle. Independent feature edits remain live and supersede older preparation.
All writes participate in the caller's authority transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import delete, func, select

from app.models.knowledge import KnowledgeCategoryRevision, KnowledgeDocument, KnowledgeStatus
from app.models.worker_feature import JobFeatureValue
from app.services.knowledge.job_feature_repository import JobFeatureValueRepo
from app.services.knowledge.project_index_repository import ProjectIndexRepo


def category_snapshot(categories, latest):
    return {
        row.category_key: {
            "active": str(row.active_revision_id) if row.active_revision_id else None,
            "latest": int(latest.get(row.id) or 0),
        }
        for row in categories
    }


def _snapshot_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if isinstance(value, uuid.UUID | Decimal) else value


async def snapshot_feature_values(db, project_id):
    rows = (
        await db.scalars(
            select(JobFeatureValue)
            .where(JobFeatureValue.project_id == project_id)
            .order_by(JobFeatureValue.feature_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).all()
    return [
        {
            column.name: _snapshot_value(getattr(row, column.name))
            for column in JobFeatureValue.__table__.columns
        }
        for row in rows
    ]


async def same_feature_intent(db, baseline, current):
    """Ignore untouched GET-created gaps, retaining actual feature edits.

    Feature-list reads backfill missing catalog rows. Their generated values
    have no source and exactly match the catalog defaults; they are not an
    administrator's new feature intent. Full snapshots remain separate so
    rollback restores those rows, identities and timestamps exactly.
    """
    catalog = await JobFeatureValueRepo(db).fetch_catalog()
    defaults = {
        str(row.id): (Decimal(str(row.default_importance_score)), priority)
        for priority, row in enumerate(catalog)
    }
    fields = (
        "feature_id", "value_text", "value_json", "strength_score", "display_priority",
        "is_highlight", "is_missing", "needs_clarification", "evidence_text", "source_document_id",
    )

    def intent(rows):
        result = []
        for row in rows:
            generated_defaults = defaults.get(row["feature_id"])
            if (
                generated_defaults is not None
                and row["value_text"] == ""
                and row["value_json"] == {}
                and row["is_missing"]
                and not row["is_highlight"]
                and not row["needs_clarification"]
                and row["source_document_id"] is None
                and row["evidence_text"] == "Chưa có thông tin trong nguồn đã tải lên."
                and (Decimal(row["strength_score"]), row["display_priority"]) == generated_defaults
            ):
                continue
            result.append({key: row[key] for key in fields})
        return result

    return intent(baseline) == intent(current)


async def restore_feature_values(db, project_id, snapshot):
    await db.execute(delete(JobFeatureValue).where(JobFeatureValue.project_id == project_id))
    for values in snapshot:
        restored = dict(values)
        for key in ("id", "project_id", "feature_id", "source_document_id"):
            if restored.get(key):
                restored[key] = uuid.UUID(restored[key])
        for key in ("created_at", "updated_at"):
            restored[key] = datetime.fromisoformat(restored[key])
        restored["strength_score"] = Decimal(restored["strength_score"])
        db.add(JobFeatureValue(**restored))
    await db.flush()


def feature_publication_state(doc, *, requires_cutover, status):
    digest = dict(doc.digest_meta or {})
    digest["project_training"] = {
        **digest.get("project_training", {}),
        "requires_cutover": requires_cutover,
    }
    digest["features"] = {"status": status}
    doc.digest_meta = digest


async def publish_training_features(db, doc):
    rows = [
        (SimpleNamespace(id=uuid.UUID(row["feature_id"])), row["value"])
        for row in doc.metadata_["project_training"].get("feature_values", [])
    ]
    await JobFeatureValueRepo(db).merge_for_project(doc.project_id, doc.id, rows, commit=False)
    await db.flush()
    await ProjectIndexRepo(db).sync_highlights(doc.project_id, commit=False)
    feature_publication_state(doc, requires_cutover=False, status="COMPLETED")


async def deferred_source_for_cutover(db, project_id, categories):
    """Only the current completed source may supply shadow-prepared features."""
    latest = dict(
        (
            await db.execute(
                select(
                    KnowledgeCategoryRevision.category_id,
                    func.max(KnowledgeCategoryRevision.revision_no),
                )
                .where(KnowledgeCategoryRevision.category_id.in_([row.id for row in categories]))
                .group_by(KnowledgeCategoryRevision.category_id)
            )
        ).all()
    )
    current = category_snapshot(categories, latest)
    source = await db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.project_id == project_id,
            KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
            KnowledgeDocument.metadata_["project_training"].astext.is_not(None),
        )
        .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if source is None:
        return None
    training = (source.metadata_ or {}).get("project_training", {})
    progress = (source.digest_meta or {}).get("project_training", {})
    if (
        source.status == KnowledgeStatus.PUBLISHED
        and progress.get("status") == "COMPLETED"
        and progress.get("requires_cutover")
        and training.get("published_snapshot") == current
        and "feature_baseline" in training
    ):
        return source
    return None


async def supersede_unadopted_deferred_features(db, project_id, *, adopted_document_id=None):
    """Close only completed, source-owned shadow intents after successful cutover."""
    sources = (
        await db.scalars(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.project_id == project_id,
                KnowledgeDocument.status == KnowledgeStatus.PUBLISHED,
                KnowledgeDocument.digest_meta["project_training"]["status"].astext == "COMPLETED",
                KnowledgeDocument.digest_meta["project_training"]["requires_cutover"].as_boolean()
                .is_(True),
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).all()
    for source in sources:
        training = (source.metadata_ or {}).get("project_training", {})
        if (
            str(source.id) != adopted_document_id
            and training.get("published_snapshot") is not None
            and "feature_baseline" in training
        ):
            feature_publication_state(source, requires_cutover=False, status="SUPERSEDED")
