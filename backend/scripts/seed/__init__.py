"""Fixture modules behind ``scripts.seed_dev`` — LOCAL dev database only.

One module per fixture domain, all sharing the clock, UUIDs, and RNG in
:mod:`scripts.seed.common` so the seed stays deterministic. ``seed_dev.py``
stays the entrypoint and re-exports everything below, so existing
``from scripts.seed_dev import make_*`` call sites keep resolving.

The ``sys.path`` bootstrap mirrors the one the monolithic script used to carry:
the fixture modules import from ``app.*``, which only resolves when the backend
directory is importable. It runs before the re-exports so every entry path into
the package — ``seed()``, a bare ``make_*`` call, or a test importing a single
fixture — sees identical path setup.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the backend package (the parent of scripts/) is importable when the
# seed is invoked from outside the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from .audit import make_audit_events  # noqa: E402
from .companies import make_companies  # noqa: E402
from .common import NOW, days_ago, hours_ago, new_uuid, rng  # noqa: E402
from .conversations import make_conversations  # noqa: E402
from .jobs import make_jobs  # noqa: E402
from .knowledge import make_knowledge_chunks, make_knowledge_documents  # noqa: E402
from .leads import (  # noqa: E402
    make_followup_tasks,
    make_lead_events,
    make_leads,
    remove_trigger_generated_leads,
)
from .message_scripts import CONVERSATION_SCRIPTS, RECRUITER_SCRIPTS  # noqa: E402
from .messages import make_messages_and_bot_runs  # noqa: E402
from .personas import make_personas  # noqa: E402
from .projects import make_projects  # noqa: E402
from .runner import seed  # noqa: E402
from .telemetry import seed_performance_metrics  # noqa: E402
from .truncate import TRUNCATE_ORDER, truncate_all  # noqa: E402
from .users import make_users  # noqa: E402
from .worker_features import make_job_feature_values, make_worker_features  # noqa: E402

__all__ = [
    "CONVERSATION_SCRIPTS",
    "NOW",
    "RECRUITER_SCRIPTS",
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
