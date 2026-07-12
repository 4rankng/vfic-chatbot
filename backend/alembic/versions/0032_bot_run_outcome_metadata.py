"""Add bot_runs.outcome_metadata JSONB for FAQ-bypass provenance + abstention.

Revision ID: 0032_bot_run_outcome_metadata
Revises: 0031_conversation_seq_trace
Create Date: 2026-07-12

Adds a nullable ``outcome_metadata`` JSONB column to ``bot_runs``. Phase 4 of the
messaging-hardening plan stores FAQ-bypass retrieval provenance here so the
similarity threshold can be tuned from production data:

  {
    "faq_document_id": "...",
    "faq_version": 7,
    "similarity_score": 0.87,
    "runner_up_score": 0.81,
    "decision_threshold": 0.82,
    "abstained": false
  }

When ``abstained`` is true, the turn fell through to the LLM because the top FAQ
match was only marginally better than the runner-up (low-confidence). The
abstention rate is surfaced on the performance dashboard to guide threshold tuning.

Reversible — the column is cleanly droppable.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0032_bot_run_outcome_metadata"
down_revision: Union[str, None] = "0031_conversation_seq_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE bot_runs ADD COLUMN IF NOT EXISTS outcome_metadata jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bot_runs DROP COLUMN IF EXISTS outcome_metadata")
