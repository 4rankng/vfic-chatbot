#!/usr/bin/env python3
"""Seed the local dev database with realistic Vietnamese recruitment data.

Idempotent: truncates all seed-owned tables then inserts fresh data.
Only safe for LOCAL development — never run against production.

Usage:
    cd backend
    python -m scripts.seed_dev

Or from repo root:
    make seed

The fixtures live in ``scripts/seed/`` (one module per fixture domain); this
module stays the entrypoint and re-exports the fixture surface so existing
``from scripts.seed_dev import make_*`` call sites keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend package is importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed import (  # noqa: E402
    NOW,
    TRUNCATE_ORDER,
    days_ago,
    hours_ago,
    make_audit_events,
    make_companies,
    make_conversations,
    make_followup_tasks,
    make_job_feature_values,
    make_jobs,
    make_knowledge_chunks,
    make_knowledge_documents,
    make_lead_events,
    make_leads,
    make_messages_and_bot_runs,
    make_personas,
    make_projects,
    make_users,
    make_worker_features,
    new_uuid,
    remove_trigger_generated_leads,
    rng,
    seed,
    seed_performance_metrics,
    truncate_all,
)

__all__ = [
    "NOW",
    "TRUNCATE_ORDER",
    "days_ago",
    "hours_ago",
    "make_audit_events",
    "make_companies",
    "make_conversations",
    "make_followup_tasks",
    "make_job_feature_values",
    "make_jobs",
    "make_knowledge_chunks",
    "make_knowledge_documents",
    "make_lead_events",
    "make_leads",
    "make_messages_and_bot_runs",
    "make_personas",
    "make_projects",
    "make_users",
    "make_worker_features",
    "new_uuid",
    "remove_trigger_generated_leads",
    "rng",
    "seed",
    "seed_performance_metrics",
    "truncate_all",
]


if __name__ == "__main__":
    seed()
