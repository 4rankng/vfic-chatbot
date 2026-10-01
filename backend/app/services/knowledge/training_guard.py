"""Fence source training checkpoints and category cutovers to their claimant."""

from datetime import UTC, datetime
import uuid

from sqlalchemy import select

from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.shared.domain.errors import ConflictError


async def ensure_training_owner(
    db, document_id: uuid.UUID, project_id: uuid.UUID, token: uuid.UUID
):
    # Uploads take this project lock too. A new source cannot commit between
    # the supersession check and a category pointer/checkpoint commit.
    await db.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    metadata = await db.scalar(
        select(KnowledgeDocument.metadata_)
        .where(KnowledgeDocument.id == document_id, KnowledgeDocument.status != KnowledgeStatus.ARCHIVED)
        .with_for_update()
    )
    training = (metadata or {}).get("project_training") or {}
    lease = training.get("lease_expires_at")
    if (
        training.get("processing_token") != str(token)
        or not lease
        or datetime.fromisoformat(lease) <= datetime.now(UTC)
    ):
        raise ConflictError("This project training attempt no longer owns its source")
    newer = await db.scalar(
        select(KnowledgeDocument.id)
        .where(
            KnowledgeDocument.project_id == project_id,
            KnowledgeDocument.status != KnowledgeStatus.ARCHIVED,
            KnowledgeDocument.created_at
            > select(KnowledgeDocument.created_at)
            .where(KnowledgeDocument.id == document_id)
            .scalar_subquery(),
            KnowledgeDocument.metadata_["project_training"].as_string().is_not(None),
        )
        .limit(1)
    )
    if newer is not None:
        raise ConflictError("A newer training source superseded this upload")
    return metadata
