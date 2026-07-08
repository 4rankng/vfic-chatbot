"""move lead materialization off the read path via a conversation trigger

Revision ID: 0025_conversation_lead_trigger
Revises: 0024_delivery_read_states
Create Date: 2026-07-08

Every list()/board() read used to take a transaction advisory lock and run an
INSERT...SELECT to backfill a stub lead row for any conversation lacking one,
which serialized all lead-board traffic deployment-wide. This migration moves
that backfill to write time: a row-level AFTER INSERT trigger on conversations
creates the stub lead the moment a conversation appears, so the read path no
longer locks or materializes.

The trigger mirrors the previous LeadRepository.materialize_conversation_leads
SQL exactly (stage='NEW', assigned_recruiter_id copied from the conversation,
idempotent via ON CONFLICT (zalo_id) DO NOTHING against the leads_zalo_id_key
unique constraint from 0001_baseline). A one-shot backfill at upgrade gives
pre-existing conversations their stub too.

CREATE FUNCTION / CREATE TRIGGER are transactional in Postgres, so this runs
inside Alembic's normal transaction (unlike ALTER TYPE ... ADD VALUE). The
downgrade drops the trigger + function; the backfilled rows are intentionally
left in place (they are valid stub leads).
"""
from alembic import op

revision = "0025_conversation_lead_trigger"
down_revision = "0024_delivery_read_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.ensure_conversation_lead()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO public.leads (
                zalo_id, lead_stage, assigned_recruiter_id, created_at, updated_at
            )
            VALUES (
                NEW.zalo_chat_id,
                'NEW'::lead_stage,
                NEW.assigned_recruiter_id,
                now(),
                NEW.updated_at
            )
            ON CONFLICT (zalo_id) DO NOTHING;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_conversation_lead_stub
        AFTER INSERT ON public.conversations
        FOR EACH ROW
        EXECUTE FUNCTION public.ensure_conversation_lead();
        """
    )
    # One-shot backfill: every pre-existing conversation gets its stub lead.
    op.execute(
        """
        INSERT INTO public.leads (
            zalo_id, lead_stage, assigned_recruiter_id, created_at, updated_at
        )
        SELECT
            c.zalo_chat_id,
            'NEW'::lead_stage,
            c.assigned_recruiter_id,
            now(),
            c.updated_at
        FROM public.conversations c
        WHERE NOT EXISTS (
            SELECT 1 FROM public.leads l WHERE l.zalo_id = c.zalo_chat_id
        )
        ON CONFLICT (zalo_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_conversation_lead_stub ON public.conversations")
    op.execute("DROP FUNCTION IF EXISTS public.ensure_conversation_lead()")
