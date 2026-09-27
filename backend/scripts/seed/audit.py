"""Audit fixture: the local-only login/CRUD trail the admin audit page reads."""

from __future__ import annotations

from datetime import timedelta

from app.models.audit import AuditEvent
from app.models.user import User

from .common import days_ago, rng


def make_audit_events(users: list[User]) -> list[AuditEvent]:
    events: list[AuditEvent] = []
    actions = [
        ("login", "user", None),
        ("create_user", "user", None),
        ("login", "user", None),
        ("publish_knowledge", "knowledge_document", None),
        ("login", "user", None),
        ("change_lead_stage", "lead", None),
        ("login", "user", None),
        ("takeover_conversation", "conversation", None),
        ("create_persona", "persona", None),
        ("login", "user", None),
        ("upload_knowledge", "knowledge_document", None),
        ("send_reply", "conversation", None),
        ("login", "user", None),
        ("change_lead_stage", "lead", None),
    ]
    for i, (action, target_type, _) in enumerate(actions):
        events.append(
            AuditEvent(
                actor_id=users[i % len(users)].id,
                action=action,
                target_type=target_type,
                payload={"ip": "127.0.0.1", "user_agent": "seed-script"},
                created_at=days_ago(rng.randint(0, 14)) + timedelta(hours=i),
            )
        )
    return events
