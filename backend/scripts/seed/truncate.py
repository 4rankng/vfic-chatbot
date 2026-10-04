"""Wipe step: reset every seed-owned table before the fixtures are inserted."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Tables to truncate in FK-safe order (leaf → root).
TRUNCATE_ORDER = [
    "audit_events",
    "password_reset_otps",
    "job_feature_values",
    "worker_feature_catalog",
    "knowledge_chunks",
    "knowledge_documents",
    "follow_up_tasks",
    "lead_events",
    "leads",
    "messages",
    "bot_runs",
    "conversations",
    "contact_channel_identities",
    "contacts",
    "jobs",
    "companies",
    "projects",
    "users",
]


def truncate_all(engine) -> None:
    """Truncate every seeded table (leaf → root, respecting FKs)."""
    # Also handle tables that may exist but don't have ORM models.
    extra = ["memories", "message_dedup"]
    with Session(engine) as session:
        for table in TRUNCATE_ORDER + extra:
            try:
                session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            except Exception:  # noqa: BLE001
                pass  # table may not exist in this migration state
        session.commit()
    print("✓ truncated all seed tables")
