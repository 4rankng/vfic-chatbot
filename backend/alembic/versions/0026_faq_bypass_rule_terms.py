"""faq bypass rule terms (required_terms / forbidden_terms)

Revision ID: 0026_faq_bypass_rule_terms
Revises: 0025_conversation_lead_trigger
Create Date: 2026-07-09

Adds two ``text[]`` columns to ``knowledge_chunks`` for the deterministic,
non-LLM FAQ bypass cascade. FAQ rows declare:

  * ``required_terms`` — every term must appear in the user query for the FAQ
    to be auto-answered.
  * ``forbidden_terms`` — if any term appears in the query the FAQ is rejected,
    even on a high-similarity match (e.g. an absence question "nghỉ 1 ngày có bị
    trừ lương không" must not surface the basic-salary FAQ).

Non-FAQ rows keep the empty default; the columns are inert without the bypass
gate in ``app.graph.runner``. Additive only — no data backfill, no index.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026_faq_bypass_rule_terms"
down_revision: Union[str, None] = "0025_conversation_lead_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "ADD COLUMN IF NOT EXISTS required_terms text[] NOT NULL DEFAULT '{}', "
        "ADD COLUMN IF NOT EXISTS forbidden_terms text[] NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "DROP COLUMN IF EXISTS forbidden_terms, "
        "DROP COLUMN IF EXISTS required_terms"
    )
