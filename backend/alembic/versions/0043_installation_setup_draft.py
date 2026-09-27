"""Add the mutable installation setup workspace and authentication authority.

Revision ID: 0043_installation_setup_draft
Revises: 0042_installation_revision_lifecycle
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0043_installation_setup_draft"
down_revision = "0042_installation_revision_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installation_setup_drafts",
        sa.Column("singleton_id", sa.SmallInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("lock_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("singleton_id = 1", name="installation_setup_draft_singleton"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="installation_setup_draft_payload_object"
        ),
        sa.CheckConstraint("lock_version >= 0", name="installation_setup_draft_lock_version"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("singleton_id"),
    )

    op.add_column(
        "installation_manifest_revisions",
        sa.Column("authentication_policy", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "installation_manifest_revisions",
        sa.Column("authentication_policy_checksum", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "installation_authentication_policy_object",
        "installation_manifest_revisions",
        "authentication_policy IS NULL OR jsonb_typeof(authentication_policy) = 'object'",
    )
    op.create_check_constraint(
        "installation_authentication_policy_checksum_sha256",
        "installation_manifest_revisions",
        "authentication_policy_checksum IS NULL OR "
        "authentication_policy_checksum ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "installation_authentication_policy_pair",
        "installation_manifest_revisions",
        "(authentication_policy IS NULL) = (authentication_policy_checksum IS NULL)",
    )

    op.add_column(
        "installation_manifest_validations",
        sa.Column("authentication_policy_checksum", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "installation_validation_authentication_checksum_sha256",
        "installation_manifest_validations",
        "authentication_policy_checksum IS NULL OR "
        "authentication_policy_checksum ~ '^[0-9a-f]{64}$'",
    )


def _data_refusal_sql() -> str:
    """A plpgsql guard that raises if the setup draft / auth authority holds data.

    This used to be a Python-side ``connection.scalar(SELECT EXISTS ...)``
    check, which made the downgrade impossible to render offline: alembic's
    ``--sql`` mode hands the migration a ``MockConnection`` that has no
    ``scalar``, so ``alembic downgrade head:base --sql`` died with an
    ``AttributeError`` instead of producing a reviewable script.

    The emitted ``DO`` block tests the same two predicates and raises the same
    refusal, so it still fires before any DDL runs inside the migration's
    transaction on a live database, and fires at apply time when the rendered
    script is run against a real database.
    """
    return """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.installation_setup_drafts LIMIT 1) OR EXISTS (
    SELECT 1 FROM public.installation_manifest_revisions
    WHERE authentication_policy IS NOT NULL OR authentication_policy_checksum IS NOT NULL
    UNION ALL
    SELECT 1 FROM public.installation_manifest_validations
    WHERE authentication_policy_checksum IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'refusing to downgrade populated installation setup or authentication authority';
  END IF;
END;
$$;
"""


def downgrade() -> None:
    op.execute(sa.text(_data_refusal_sql()))

    op.drop_constraint(
        "installation_validation_authentication_checksum_sha256",
        "installation_manifest_validations",
        type_="check",
    )
    op.drop_column("installation_manifest_validations", "authentication_policy_checksum")

    op.drop_constraint(
        "installation_authentication_policy_pair",
        "installation_manifest_revisions",
        type_="check",
    )
    op.drop_constraint(
        "installation_authentication_policy_checksum_sha256",
        "installation_manifest_revisions",
        type_="check",
    )
    op.drop_constraint(
        "installation_authentication_policy_object",
        "installation_manifest_revisions",
        type_="check",
    )
    op.drop_column("installation_manifest_revisions", "authentication_policy_checksum")
    op.drop_column("installation_manifest_revisions", "authentication_policy")
    op.drop_table("installation_setup_drafts")
