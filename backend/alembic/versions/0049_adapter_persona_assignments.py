"""Scope personas to canonical adapters instead of projects.

Revision ID: 0049_adapter_persona_assignments
Revises: 0048_project_owned_knowledge_modes

Project-level persona selection was an invalid authority model. This revision
removes ``projects.default_persona_id`` and ``personas.project_id``, replaces
them with provider-scoped overrides keyed by canonical adapter id, and keeps
the single active global default on ``personas.is_active``.
"""

from alembic import op
import sqlalchemy as sa


revision = "0049_adapter_persona_assignments"
down_revision = "0048_project_owned_knowledge_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    ORDER BY
                        CASE WHEN project_id IS NULL THEN 0 ELSE 1 END,
                        updated_at DESC,
                        created_at DESC,
                        id DESC
                ) AS rn
            FROM public.personas
            WHERE is_active
        )
        UPDATE public.personas AS p
        SET is_active = false
        FROM ranked
        WHERE p.id = ranked.id
          AND ranked.rn > 1
        """
    )
    op.execute("DROP INDEX IF EXISTS public.personas_one_active_global")
    op.execute(
        """
        CREATE UNIQUE INDEX personas_one_active
          ON public.personas ((1)) WHERE is_active;
        """
    )

    op.create_table(
        "adapter_persona_assignments",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "provider IN ('zalo_bot', 'zalo_oa', 'facebook_messenger')",
            name="adapter_persona_assignments_provider_valid",
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provider"),
    )
    op.create_index(
        "ix_adapter_persona_assignments_persona",
        "adapter_persona_assignments",
        ["persona_id"],
    )
    op.execute(
        """
        CREATE TRIGGER adapter_persona_assignments_touch
          BEFORE UPDATE ON public.adapter_persona_assignments
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
        """
    )

    op.drop_column("projects", "default_persona_id")
    op.drop_column("personas", "project_id")


def downgrade() -> None:
    op.add_column("personas", sa.Column("project_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "personas_project_id_fkey",
        "personas",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column("projects", sa.Column("default_persona_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "projects_default_persona_id_fkey",
        "projects",
        "personas",
        ["default_persona_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute("DROP INDEX IF EXISTS public.personas_one_active")
    op.execute(
        """
        CREATE UNIQUE INDEX personas_one_active_global
          ON public.personas ((1)) WHERE is_active AND project_id IS NULL;
        """
    )

    # Legacy project/persona assignments are intentionally not restored; the
    # upgrade removed an invalid authority model and only recreates nullable
    # columns for schema compatibility on downgrade.
    op.execute(
        "DROP TRIGGER IF EXISTS adapter_persona_assignments_touch "
        "ON public.adapter_persona_assignments"
    )
    op.drop_index("ix_adapter_persona_assignments_persona", table_name="adapter_persona_assignments")
    op.drop_table("adapter_persona_assignments")
