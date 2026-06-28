"""Add semi-auto conversation mode.

Revision ID: 0007_conversation_semi_auto
Revises: 0006_publish_knowledge_status
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

revision = "0007_conversation_semi_auto"
down_revision = "0006_publish_knowledge_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE conversation_mode ADD VALUE IF NOT EXISTS 'SEMI_AUTO'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be dropped safely without rebuilding the type.
    # Keep the value in place on downgrade.
    pass
