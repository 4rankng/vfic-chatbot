"""Replace lead_stage enum with the four-stage recruitment flow.

Revision ID: 0017_replace_lead_stage_flow
Revises: 0016_query_perf_indexes
Create Date: 2026-06-30
"""
from alembic import op

revision = "0017_replace_lead_stage_flow"
down_revision = "0016_query_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.leads ALTER COLUMN lead_stage DROP DEFAULT;

        ALTER TYPE lead_stage RENAME TO lead_stage_old;
        CREATE TYPE lead_stage AS ENUM ('NEW', 'CONTACTING', 'REGISTERED', 'SKIPPED');

        ALTER TABLE public.leads
          ALTER COLUMN lead_stage TYPE lead_stage
          USING (
            CASE lead_stage::text
              WHEN 'NEW' THEN 'NEW'
              WHEN 'ENGAGED' THEN 'CONTACTING'
              WHEN 'QUALIFIED' THEN 'REGISTERED'
              WHEN 'APPLIED' THEN 'REGISTERED'
              WHEN 'HIRED' THEN 'REGISTERED'
              WHEN 'LOST' THEN 'SKIPPED'
              WHEN 'UNQUALIFIED' THEN 'SKIPPED'
              ELSE 'NEW'
            END
          )::lead_stage;

        ALTER TABLE public.leads ALTER COLUMN lead_stage SET DEFAULT 'NEW';
        DROP TYPE lead_stage_old;
        """
    )
    # ALTER COLUMN TYPE drops every index on the column, so the stage index the
    # baseline defined must be recreated. leads is the hot recruiter-facing
    # table, so the rebuild is CONCURRENTLY (plain CREATE INDEX write-blocks
    # leads for the whole build while migrations run mid-deploy); it runs in
    # its own autocommit block because CONCURRENTLY cannot sit inside the
    # transaction that just swapped the enum.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS leads_stage_idx "
            "ON public.leads (lead_stage)"
        )


def downgrade() -> None:
    """Lossy: QUALIFIED/APPLIED/HIRED all collapsed to REGISTERED on upgrade,
    so REGISTERED maps back only to APPLIED — original QUALIFIED and HIRED
    values are irrecoverable. Restore from backup if rollback is needed."""
    op.execute(
        """
        ALTER TABLE public.leads ALTER COLUMN lead_stage DROP DEFAULT;

        ALTER TYPE lead_stage RENAME TO lead_stage_new;
        CREATE TYPE lead_stage AS ENUM ('NEW','ENGAGED','QUALIFIED','APPLIED','HIRED','LOST','UNQUALIFIED');

        ALTER TABLE public.leads
          ALTER COLUMN lead_stage TYPE lead_stage
          USING (
            CASE lead_stage::text
              WHEN 'NEW' THEN 'NEW'
              WHEN 'CONTACTING' THEN 'ENGAGED'
              WHEN 'REGISTERED' THEN 'APPLIED'
              WHEN 'SKIPPED' THEN 'UNQUALIFIED'
              ELSE 'NEW'
            END
          )::lead_stage;

        ALTER TABLE public.leads ALTER COLUMN lead_stage SET DEFAULT 'NEW';
        DROP TYPE lead_stage_new;

        -- Recreate the stage index dropped by ALTER COLUMN TYPE.
        CREATE INDEX IF NOT EXISTS leads_stage_idx ON public.leads (lead_stage);
        """
    )
