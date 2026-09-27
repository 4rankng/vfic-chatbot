"""Add dormant generic Contact/Case kernel and immutable workflows.

Revision ID: 0044_generic_contact_case_kernel
Revises: 0043_installation_setup_draft
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0044_generic_contact_case_kernel"
down_revision = "0043_installation_setup_draft"
branch_labels = None
depends_on = None


_GUARDED_TABLES = (
    "case_followups",
    "case_notes",
    "case_tag_assignments",
    "cases",
    "contact_channel_identities",
    "contacts",
    "case_workflow_transitions",
    "case_tag_definitions",
    "case_workflow_stages",
    "case_workflow_versions",
)

def upgrade() -> None:
    op.create_table(
        "case_workflow_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pack_key", sa.String(64), nullable=False),
        sa.Column("workflow_key", sa.String(64), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("case_attribute_schema", postgresql.JSONB(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pack_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="case_workflow_pack_key_canonical"
        ),
        sa.CheckConstraint(
            "workflow_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="case_workflow_key_canonical"
        ),
        sa.CheckConstraint("version_no > 0", name="case_workflow_version_positive"),
        sa.CheckConstraint("schema_version = 1", name="case_workflow_schema_v1"),
        sa.CheckConstraint(
            "jsonb_typeof(case_attribute_schema) = 'object'", name="case_workflow_attributes_object"
        ),
        sa.CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="case_workflow_checksum_sha256"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pack_key", "workflow_key", "version_no", name="uq_case_workflow_version"
        ),
        sa.UniqueConstraint(
            "pack_key", "workflow_key", "checksum", name="uq_case_workflow_checksum"
        ),
        sa.UniqueConstraint("id", "checksum", name="uq_case_workflow_id_checksum"),
    )
    op.create_index(
        "ix_case_workflow_versions_lookup",
        "case_workflow_versions",
        ["pack_key", "workflow_key", sa.text("version_no DESC")],
    )

    op.create_table(
        "case_workflow_stages",
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("stage_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("is_initial", sa.Boolean(), nullable=False),
        sa.Column("is_terminal", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "stage_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="case_workflow_stage_key_canonical"
        ),
        sa.CheckConstraint("position >= 0", name="case_workflow_stage_position_nonnegative"),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"], ["case_workflow_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("workflow_version_id", "stage_key"),
        sa.UniqueConstraint(
            "workflow_version_id", "position", name="uq_case_workflow_stage_position"
        ),
    )
    op.create_index(
        "uq_case_workflow_one_initial",
        "case_workflow_stages",
        ["workflow_version_id"],
        unique=True,
        postgresql_where=sa.text("is_initial"),
    )

    op.create_table(
        "case_workflow_transitions",
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("from_stage_key", sa.String(64), nullable=False),
        sa.Column("to_stage_key", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "from_stage_key <> to_stage_key", name="case_workflow_transition_not_self"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "from_stage_key"],
            ["case_workflow_stages.workflow_version_id", "case_workflow_stages.stage_key"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "to_stage_key"],
            ["case_workflow_stages.workflow_version_id", "case_workflow_stages.stage_key"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workflow_version_id", "from_stage_key", "to_stage_key"),
    )
    op.create_table(
        "case_tag_definitions",
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("tag_key", sa.String(48), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("tone", sa.String(16), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("tag_key ~ '^[a-z0-9][a-z0-9._-]*$'", name="case_tag_key_canonical"),
        sa.CheckConstraint(
            "tone IN ('neutral','info','success','warning','danger')", name="case_tag_tone_closed"
        ),
        sa.CheckConstraint("position >= 0", name="case_tag_position_nonnegative"),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"], ["case_workflow_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("workflow_version_id", "tag_key"),
        sa.UniqueConstraint("workflow_version_id", "position", name="uq_case_tag_position"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_immutable_case_workflow_write()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          parent_is_current_transaction boolean;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            SELECT EXISTS (
              SELECT 1
              FROM case_workflow_versions
              WHERE id = NEW.workflow_version_id
                AND xmin::text = pg_current_xact_id()::text
            ) INTO parent_is_current_transaction;
            IF parent_is_current_transaction THEN
              RETURN NEW;
            END IF;
            RAISE EXCEPTION '% belongs to a published immutable workflow', TG_TABLE_NAME
              USING ERRCODE = '55000';
          END IF;
          IF TG_TABLE_NAME = 'case_workflow_versions' AND TG_OP = 'UPDATE' THEN
            IF (to_jsonb(NEW) - 'created_by') = (to_jsonb(OLD) - 'created_by')
               AND OLD.created_by IS NOT NULL
               AND NEW.created_by IS NULL THEN
              RETURN NEW;
            END IF;
          END IF;
          RAISE EXCEPTION '% is immutable', TG_TABLE_NAME USING ERRCODE = '55000';
        END;
        $$;
        CREATE TRIGGER case_workflow_versions_immutable BEFORE UPDATE OR DELETE ON case_workflow_versions FOR EACH ROW EXECUTE FUNCTION reject_immutable_case_workflow_write();
        CREATE TRIGGER case_workflow_stages_immutable BEFORE INSERT OR UPDATE OR DELETE ON case_workflow_stages FOR EACH ROW EXECUTE FUNCTION reject_immutable_case_workflow_write();
        CREATE TRIGGER case_workflow_transitions_immutable BEFORE INSERT OR UPDATE OR DELETE ON case_workflow_transitions FOR EACH ROW EXECUTE FUNCTION reject_immutable_case_workflow_write();
        CREATE TRIGGER case_tag_definitions_immutable BEFORE INSERT OR UPDATE OR DELETE ON case_tag_definitions FOR EACH ROW EXECUTE FUNCTION reject_immutable_case_workflow_write();
        """
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("display_name", sa.String(160)),
        sa.Column("primary_email", sa.String(254)),
        sa.Column("primary_phone", sa.String(32)),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("locale", sa.String(35)),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
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
        sa.CheckConstraint("version > 0", name="contact_version_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_updated", "contacts", [sa.text("updated_at DESC"), "id"])
    op.create_table(
        "contact_channel_identities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_key", sa.String(128), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
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
        sa.CheckConstraint(
            "provider ~ '^[a-z0-9][a-z0-9._-]*$'", name="contact_channel_provider_canonical"
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "account_key", "external_id", name="uq_contact_channel_authority"
        ),
        sa.UniqueConstraint("id", "contact_id", name="uq_contact_channel_contact"),
    )
    op.create_index("ix_contact_channel_contact", "contact_channel_identities", ["contact_id"])

    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_no", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("workflow_checksum", sa.String(64), nullable=False),
        sa.Column("stage_key", sa.String(64), nullable=False),
        sa.Column("lifecycle", sa.String(16), server_default="OPEN", nullable=False),
        sa.Column("subject", sa.String(240)),
        sa.Column("assigned_user_id", sa.UUID()),
        sa.Column(
            "attributes", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "lifecycle IN ('OPEN','CLOSED','CANCELLED')", name="case_lifecycle_closed"
        ),
        sa.CheckConstraint("version > 0", name="case_version_positive"),
        sa.CheckConstraint("jsonb_typeof(attributes) = 'object'", name="case_attributes_object"),
        sa.CheckConstraint(
            "(lifecycle = 'OPEN') = (closed_at IS NULL)", name="case_lifecycle_closed_at"
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "workflow_checksum"],
            ["case_workflow_versions.id", "case_workflow_versions.checksum"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "stage_key"],
            ["case_workflow_stages.workflow_version_id", "case_workflow_stages.stage_key"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_no"),
        sa.UniqueConstraint("id", "workflow_version_id", name="uq_case_workflow"),
    )
    op.create_index("ix_cases_contact_updated", "cases", ["contact_id", sa.text("updated_at DESC")])
    op.create_index(
        "ix_cases_assignee_lifecycle_updated",
        "cases",
        ["assigned_user_id", "lifecycle", sa.text("updated_at DESC")],
    )
    op.create_index(
        "ix_cases_workflow_stage_updated",
        "cases",
        ["workflow_version_id", "stage_key", sa.text("updated_at DESC")],
    )
    op.create_table(
        "case_tag_assignments",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("workflow_version_id", sa.UUID(), nullable=False),
        sa.Column("tag_key", sa.String(48), nullable=False),
        sa.Column("created_by", sa.UUID()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "workflow_version_id"],
            ["cases.id", "cases.workflow_version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "tag_key"],
            ["case_tag_definitions.workflow_version_id", "case_tag_definitions.tag_key"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("case_id", "tag_key"),
    )
    op.create_table(
        "case_notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_case_notes_case_created",
        "case_notes",
        ["case_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_table(
        "case_followups",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("assigned_user_id", sa.UUID()),
        sa.Column("created_by", sa.UUID()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
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
        sa.CheckConstraint(
            "status IN ('PENDING','COMPLETED','CANCELLED')", name="case_followup_status_closed"
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="case_followup_completed_at"
        ),
        sa.CheckConstraint("version > 0", name="case_followup_version_positive"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_case_followups_case_created",
        "case_followups",
        ["case_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_case_followups_pending_due",
        "case_followups",
        ["due_at", "id"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.add_column("installation_manifest_revisions", sa.Column("workflow_version_id", sa.UUID()))
    op.add_column(
        "installation_manifest_revisions", sa.Column("workflow_version_checksum", sa.String(64))
    )
    op.create_check_constraint(
        "installation_workflow_version_pair",
        "installation_manifest_revisions",
        "(workflow_version_id IS NULL) = (workflow_version_checksum IS NULL)",
    )
    op.create_check_constraint(
        "installation_workflow_version_checksum_sha256",
        "installation_manifest_revisions",
        "workflow_version_checksum IS NULL OR workflow_version_checksum ~ '^[0-9a-f]{64}$'",
    )
    op.create_foreign_key(
        "fk_installation_revision_workflow_version",
        "installation_manifest_revisions",
        "case_workflow_versions",
        ["workflow_version_id", "workflow_version_checksum"],
        ["id", "checksum"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "installation_manifest_validations", sa.Column("workflow_version_checksum", sa.String(64))
    )
    op.create_check_constraint(
        "installation_validation_workflow_version_sha256",
        "installation_manifest_validations",
        "workflow_version_checksum IS NULL OR workflow_version_checksum ~ '^[0-9a-f]{64}$'",
    )

    op.add_column("conversations", sa.Column("contact_id", sa.UUID()))
    op.add_column("conversations", sa.Column("channel_identity_id", sa.UUID()))
    op.create_check_constraint(
        "conversation_identity_requires_contact",
        "conversations",
        "channel_identity_id IS NULL OR contact_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_conversation_contact",
        "conversations",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_conversation_channel_contact",
        "conversations",
        "contact_channel_identities",
        ["channel_identity_id", "contact_id"],
        ["id", "contact_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_conversations_contact",
        "conversations",
        ["contact_id"],
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversations_channel_identity",
        "conversations",
        ["channel_identity_id"],
        unique=True,
        postgresql_where=sa.text("channel_identity_id IS NOT NULL"),
    )


def _data_refusal_sql() -> str:
    """A plpgsql guard that raises if the kernel this revision drops holds data.

    This used to be a Python-side ``connection.scalar(SELECT EXISTS ...)``
    check, which made the downgrade impossible to render offline: alembic's
    ``--sql`` mode hands the migration a ``MockConnection`` that has no
    ``scalar``, so ``alembic downgrade head:base --sql`` died with an
    ``AttributeError`` instead of producing a reviewable script.

    Emitting the same checks as a ``DO`` block keeps the guard just as strict
    online (it raises before any DDL runs, inside the migration's transaction)
    while rendering as ordinary SQL offline, where it fires at apply time
    against whichever database the operator runs the script on.
    """
    table_checks = "\n".join(
        "  IF EXISTS (SELECT 1 FROM public."
        + table
        + " LIMIT 1) THEN populated := array_append(populated, '"
        + table
        + "'); END IF;"
        for table in _GUARDED_TABLES
    )
    return (
        "DO $$\n"
        "DECLARE\n"
        "  populated text[] := ARRAY[]::text[];\n"
        "BEGIN\n"
        f"{table_checks}\n"
        "  IF cardinality(populated) > 0 THEN\n"
        "    RAISE EXCEPTION 'refusing to downgrade populated generic kernel: %', populated;\n"
        "  END IF;\n"
        "  IF EXISTS (SELECT 1 FROM public.conversations"
        " WHERE contact_id IS NOT NULL OR channel_identity_id IS NOT NULL) THEN\n"
        "    RAISE EXCEPTION 'refusing to downgrade: conversations reference the contact kernel';\n"
        "  END IF;\n"
        "  IF EXISTS ("
        " SELECT 1 FROM public.installation_manifest_revisions"
        " WHERE workflow_version_id IS NOT NULL OR workflow_version_checksum IS NOT NULL"
        " UNION ALL"
        " SELECT 1 FROM public.installation_manifest_validations"
        " WHERE workflow_version_checksum IS NOT NULL) THEN\n"
        "    RAISE EXCEPTION 'refusing to downgrade: installation manifests pin a workflow version';\n"
        "  END IF;\n"
        "END;\n"
        "$$;"
    )


def downgrade() -> None:
    op.execute(sa.text(_data_refusal_sql()))

    op.drop_index("uq_conversations_channel_identity", table_name="conversations")
    op.drop_index("ix_conversations_contact", table_name="conversations")
    op.drop_constraint("fk_conversation_channel_contact", "conversations", type_="foreignkey")
    op.drop_constraint("fk_conversation_contact", "conversations", type_="foreignkey")
    op.drop_constraint("conversation_identity_requires_contact", "conversations", type_="check")
    op.drop_column("conversations", "channel_identity_id")
    op.drop_column("conversations", "contact_id")
    op.drop_constraint(
        "installation_validation_workflow_version_sha256",
        "installation_manifest_validations",
        type_="check",
    )
    op.drop_column("installation_manifest_validations", "workflow_version_checksum")
    op.drop_constraint(
        "fk_installation_revision_workflow_version",
        "installation_manifest_revisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "installation_workflow_version_checksum_sha256",
        "installation_manifest_revisions",
        type_="check",
    )
    op.drop_constraint(
        "installation_workflow_version_pair", "installation_manifest_revisions", type_="check"
    )
    op.drop_column("installation_manifest_revisions", "workflow_version_checksum")
    op.drop_column("installation_manifest_revisions", "workflow_version_id")
    op.drop_table("case_followups")
    op.drop_table("case_notes")
    op.drop_table("case_tag_assignments")
    op.drop_table("cases")
    op.drop_table("contact_channel_identities")
    op.drop_table("contacts")
    op.drop_table("case_workflow_transitions")
    op.drop_table("case_tag_definitions")
    op.drop_table("case_workflow_stages")
    op.drop_table("case_workflow_versions")
    op.execute("DROP FUNCTION reject_immutable_case_workflow_write()")
