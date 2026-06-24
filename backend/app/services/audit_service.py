"""Append-only audit logging.

Central helper so every privileged action is recorded the same way. The caller is
responsible for committing the session (record_audit only flushes, so it can be
composed with other writes in one transaction).
"""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Insert an audit_events row and flush it (does not commit)."""
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
    )
    db.add(event)
    await db.flush()
    return event
