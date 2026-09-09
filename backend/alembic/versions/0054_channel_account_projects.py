"""Multi-Page Facebook Messenger: per-account active uniqueness + channel_account_projects.

Revision ID: 0054_channel_account_projects
Revises: 0053_single_page_external_source_sync_state
Create Date: 2026-09-08

Multi-Page rollout (plan 260908-1341), backend Phase 1. Two schema changes:

1. Relax ``uq_channel_accounts_one_active_facebook_messenger`` ("at most one
   ACTIVE facebook_messenger row GLOBALLY") to per-(provider, account_key): a
   given Page cannot be active twice, but many different Pages may each be
   independently active. The V1 index was the hard DB-level blocker for
   multi-Page.
2. New ``channel_account_projects`` join table: the many-to-many Page/Project
   mapping that scopes each conversation's Project catalog to its Page.

Cascade decisions (recorded; runtime mirrors them):
- Page disconnect does NOT clear mappings (kept so a reconnect resumes the
  previous assignment without admin re-entry). Disconnect marks the account
  INACTIVE, and INACTIVE accounts never resolve webhook/send authority, so a
  disconnected Page serves nothing regardless of its mappings.
- Project deactivation keeps the mapping; catalog queries filter
  ``projects.is_active`` themselves.
- FK ON DELETE CASCADE covers only actual row deletion.

Backfill (run-brief decision D2): the existing ACTIVE facebook_messenger Page
is assigned ALL currently-active Projects, preserving pre-migration single-Page
behavior exactly (AC #7: zero regression).

Downgrade is FAIL-CLOSED: refuses while more than one ACTIVE facebook_messenger
row exists (multi-Page state cannot revert to the single-Page constraint
without data loss). With <=1 active Page the revert is clean.

This migration is hand-written and approval-gated (AGENTS.md protected
operations; approved as plan scope by the run brief). No network calls.
"""

from alembic import op
import sqlalchemy as sa

revision = "0054_channel_account_projects"
down_revision = "0053_single_page_external_source_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Relax the V1 single-active-Page partial unique index.
    op.execute("DROP INDEX IF EXISTS public.uq_channel_accounts_one_active_facebook_messenger")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_channel_accounts_one_active_per_account
            ON public.channel_accounts (provider, account_key)
            WHERE status = 'ACTIVE'
        """
    )

    # 2. The Page/Project mapping join table.
    op.create_table(
        "channel_account_projects",
        sa.Column("channel_account_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("channel_account_id", "project_id"),
        sa.ForeignKeyConstraint(
            ["channel_account_id"],
            ["channel_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_channel_account_projects_project_id",
        "channel_account_projects",
        ["project_id"],
    )

    # 3. Backfill per decision D2: existing ACTIVE facebook_messenger Page is
    #    assigned ALL currently-active Projects (zero-regression backfill).
    op.execute(
        """
        INSERT INTO public.channel_account_projects
            (channel_account_id, project_id, created_at)
        SELECT ca.id, p.id, now()
        FROM public.channel_accounts ca
        CROSS JOIN public.projects p
        WHERE ca.provider = 'facebook_messenger'
          AND ca.status = 'ACTIVE'
          AND p.is_active
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # FAIL-CLOSED: multi-Page state cannot revert to the single-Page world.
    op.execute(
        """
        DO $$
        DECLARE active_fb INTEGER;
        BEGIN
            SELECT COUNT(*) INTO active_fb
            FROM public.channel_accounts
            WHERE provider = 'facebook_messenger' AND status = 'ACTIVE';
            IF active_fb > 1 THEN
                RAISE EXCEPTION
                    'REFUSE 0054 downgrade: % ACTIVE facebook_messenger rows exist. '
                    'Disconnect Pages until one remains before downgrading; '
                    'multi-Page state cannot be represented under the V1 constraint.',
                    active_fb
                    USING ERRCODE = 'check_violation';
            END IF;
        END;
        $$;
        """
    )

    # Mapping data is dropped with the table; the <=1-active-Page guard above
    # means the surviving assignment set (if any) maps the one active Page to a
    # subset of active Projects, which the V1 runtime semantics re-interpret
    # safely (V1 ignores the mapping entirely).
    op.drop_table("channel_account_projects")

    # Restore the V1 single-active-Page constraint.
    op.execute("DROP INDEX IF EXISTS public.uq_channel_accounts_one_active_per_account")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_channel_accounts_one_active_facebook_messenger
            ON public.channel_accounts (provider)
            WHERE provider = 'facebook_messenger' AND status = 'ACTIVE'
        """
    )
