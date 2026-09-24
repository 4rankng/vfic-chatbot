"""Backfill lead cards for existing conversations.

Revision ID: 0018_backfill_conversation_leads
Revises: 0017_replace_lead_stage_flow
Create Date: 2026-06-30
"""
from alembic import op

revision = "0018_backfill_conversation_leads"
down_revision = "0017_replace_lead_stage_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO public.leads (
          zalo_id,
          lead_stage,
          assigned_recruiter_id,
          created_at,
          updated_at
        )
        SELECT
          c.zalo_chat_id,
          'NEW'::lead_stage,
          c.assigned_recruiter_id,
          c.created_at,
          c.updated_at
        FROM public.conversations c
        WHERE NOT EXISTS (
          SELECT 1
          FROM public.leads l
          WHERE l.zalo_id = c.zalo_chat_id
        )
        ON CONFLICT (zalo_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    # downgrade: INTENTIONAL_NOOP — these are real candidate lead records
    # backfilled from actual chats; a downgrade must not delete them.
    pass
