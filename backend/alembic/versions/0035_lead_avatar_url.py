"""Add nullable leads.avatar_url for Zalo OA profile enrichment.

Revision ID: 0035_lead_avatar_url
Revises: 0034_messages_delivery_review_index
Create Date: 2026-07-12

The recruiter console previously rendered only initials/icons for candidate
avatars because Zalo profile images were never fetched or persisted. A
best-effort OA profile enrichment job (``ProfileEnrichmentService``) now looks
up ``GET /v3.0/oa/user/detail`` and stores the best documented image URL on
the lead. This migration adds the single nullable text column that holds it.

Additive and fully reversible: ``upgrade`` adds ``avatar_url`` (nullable text,
no default, no NOT NULL), ``downgrade`` drops it. No data backfill is needed
(existing rows simply have ``NULL`` and keep the initials fallback). No index
is required — avatars are read alongside the lead row, never filtered on.

Human-approved per AGENTS.md §13 (additive migration on a protected path).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0035_lead_avatar_url"
down_revision = "0034_messages_delivery_review_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("avatar_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "avatar_url")
