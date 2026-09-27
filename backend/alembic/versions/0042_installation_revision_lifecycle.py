"""Add immutable installation revision lifecycle and persona versions.

Revision ID: 0042_installation_revision_lifecycle
Revises: 0041_version_scope_typed_authority
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0042_installation_revision_lifecycle"
down_revision = "0041_version_scope_typed_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("followup_rules", postgresql.JSONB(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version_no > 0", name="persona_versions_positive_version"),
        sa.CheckConstraint(
            "jsonb_typeof(followup_rules) = 'object'",
            name="persona_versions_followup_rules_object",
        ),
        sa.CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="persona_versions_checksum_sha256"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("persona_id", "version_no", name="persona_versions_identity_key"),
    )
    op.create_index("ix_persona_versions_persona_id", "persona_versions", ["persona_id"])

    op.create_table(
        "installation_manifest_revisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("revision_no", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("predecessor_id", sa.UUID(), nullable=True),
        sa.Column("pack_key", sa.String(length=64), nullable=False),
        sa.Column("pack_version", sa.String(length=32), nullable=False),
        sa.Column("pack_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=64), nullable=False),
        sa.Column("customer_identity", postgresql.JSONB(), nullable=False),
        sa.Column("branding", postgresql.JSONB(), nullable=False),
        sa.Column("locale", sa.String(length=35), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("terminology", postgresql.JSONB(), nullable=False),
        sa.Column("workflow_policy", postgresql.JSONB(), nullable=False),
        sa.Column("workflow_policy_checksum", sa.String(length=64), nullable=False),
        sa.Column("capability_ids", postgresql.JSONB(), nullable=False),
        sa.Column("persona_version_id", sa.UUID(), nullable=False),
        sa.Column("template_version_refs", postgresql.JSONB(), nullable=False),
        sa.Column("provider_policy", postgresql.JSONB(), nullable=False),
        sa.Column("provider_policy_checksum", sa.String(length=64), nullable=False),
        sa.Column("integration_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(customer_identity) = 'object'",
            name="installation_customer_identity_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(branding) = 'object'", name="installation_branding_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(terminology) = 'object'", name="installation_terminology_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(workflow_policy) = 'object'",
            name="installation_workflow_policy_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(capability_ids) = 'array'",
            name="installation_capability_ids_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(template_version_refs) = 'array'",
            name="installation_template_refs_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(provider_policy) = 'object'",
            name="installation_provider_policy_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(integration_requirements) = 'array'",
            name="installation_integration_requirements_array",
        ),
        sa.CheckConstraint(
            "pack_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND manifest_checksum ~ '^[0-9a-f]{64}$' "
            "AND workflow_policy_checksum ~ '^[0-9a-f]{64}$' "
            "AND provider_policy_checksum ~ '^[0-9a-f]{64}$'",
            name="installation_revision_checksums_sha256",
        ),
        sa.CheckConstraint(
            "pack_key ~ '^[a-z0-9][a-z0-9._-]*$'",
            name="installation_revision_pack_key_canonical",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="installation_revision_currency_uppercase",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["persona_version_id"], ["persona_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_id"], ["installation_manifest_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision_no"),
    )
    op.create_index(
        "ix_installation_manifest_revisions_predecessor_id",
        "installation_manifest_revisions",
        ["predecessor_id"],
    )

    op.create_table(
        "installation_manifest_validations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("validator_version", sa.String(length=32), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("issues", postgresql.JSONB(), nullable=False),
        sa.Column("reference_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=64), nullable=False),
        sa.Column("pack_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("persona_checksum", sa.String(length=64), nullable=False),
        sa.Column("workflow_policy_checksum", sa.String(length=64), nullable=False),
        sa.Column("provider_policy_checksum", sa.String(length=64), nullable=False),
        sa.Column("template_checksums", postgresql.JSONB(), nullable=False),
        sa.Column("active_kb_vector", postgresql.JSONB(), nullable=False),
        sa.Column("validated_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(issues) = 'array'", name="installation_validation_issues_array"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reference_snapshot) = 'object'",
            name="installation_validation_snapshot_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(template_checksums) = 'object'",
            name="installation_validation_templates_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(active_kb_vector) = 'array'",
            name="installation_validation_kb_vector_array",
        ),
        sa.CheckConstraint(
            "manifest_checksum ~ '^[0-9a-f]{64}$' "
            "AND pack_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND persona_checksum ~ '^[0-9a-f]{64}$' "
            "AND workflow_policy_checksum ~ '^[0-9a-f]{64}$' "
            "AND provider_policy_checksum ~ '^[0-9a-f]{64}$'",
            name="installation_validation_checksums_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["installation_manifest_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["validated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_installation_manifest_validations_revision_id",
        "installation_manifest_validations",
        ["revision_id"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_immutable_installation_write()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE'
             AND (to_jsonb(NEW) - TG_ARGV[0]) = (to_jsonb(OLD) - TG_ARGV[0])
             AND (to_jsonb(OLD) -> TG_ARGV[0]) <> 'null'::jsonb
             AND (to_jsonb(NEW) -> TG_ARGV[0]) = 'null'::jsonb THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
            USING ERRCODE = '55000';
        END;
        $$;

        CREATE TRIGGER persona_versions_immutable
          BEFORE UPDATE OR DELETE ON persona_versions
          FOR EACH ROW EXECUTE FUNCTION reject_immutable_installation_write('created_by');
        CREATE TRIGGER installation_manifest_revisions_immutable
          BEFORE UPDATE OR DELETE ON installation_manifest_revisions
          FOR EACH ROW EXECUTE FUNCTION reject_immutable_installation_write('created_by');
        CREATE TRIGGER installation_manifest_validations_immutable
          BEFORE UPDATE OR DELETE ON installation_manifest_validations
          FOR EACH ROW EXECUTE FUNCTION reject_immutable_installation_write('validated_by');
        """
    )

    op.create_table(
        "installation_state",
        sa.Column("singleton_id", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("current_revision_id", sa.UUID(), nullable=False),
        sa.Column("validated_revision_id", sa.UUID(), nullable=True),
        sa.Column("active_revision_id", sa.UUID(), nullable=True),
        sa.Column("active_validation_id", sa.UUID(), nullable=True),
        sa.Column("previous_active_revision_id", sa.UUID(), nullable=True),
        sa.Column("authority_generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("lock_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.UUID(), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_by", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("singleton_id = 1", name="installation_state_singleton"),
        sa.CheckConstraint("authority_generation >= 0", name="installation_state_generation"),
        sa.CheckConstraint("lock_version >= 0", name="installation_state_lock_version"),
        sa.CheckConstraint(
            "lifecycle IN ('DRAFT','VALIDATED','ACTIVE','SUSPENDED')",
            name="installation_state_lifecycle",
        ),
        sa.CheckConstraint(
            "lifecycle NOT IN ('ACTIVE','SUSPENDED') OR "
            "(active_revision_id IS NOT NULL AND active_validation_id IS NOT NULL)",
            name="installation_state_active_pointers",
        ),
        sa.CheckConstraint(
            "lifecycle <> 'VALIDATED' OR validated_revision_id IS NOT NULL",
            name="installation_state_validated_pointer",
        ),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["suspended_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["active_revision_id"], ["installation_manifest_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["active_validation_id"], ["installation_manifest_validations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["current_revision_id"], ["installation_manifest_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["previous_active_revision_id"],
            ["installation_manifest_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validated_revision_id"], ["installation_manifest_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("singleton_id"),
    )


_GUARDED_TABLES = (
    "installation_state",
    "installation_manifest_validations",
    "installation_manifest_revisions",
    "persona_versions",
)


def _data_refusal_sql() -> str:
    """A plpgsql guard that raises if the immutable installation tables hold data.

    This used to be a Python-side ``connection.scalar(SELECT EXISTS ...)``
    check, which made the downgrade impossible to render offline: alembic's
    ``--sql`` mode hands the migration a ``MockConnection`` that has no
    ``scalar``, so ``alembic downgrade head:base --sql`` died with an
    ``AttributeError`` instead of producing a reviewable script.

    The emitted ``DO`` block tests the same predicate and raises the same
    refusal for the same tables, so it still fires before any DDL runs inside
    the migration's transaction when a live database is being downgraded. In
    offline mode it is rendered as ordinary SQL and fires against whichever
    database the operator runs the script on.
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
        "    RAISE EXCEPTION 'refusing to downgrade populated immutable installation tables: %',"
        " array_to_string(populated, ', ');\n"
        "  END IF;\n"
        "END;\n"
        "$$;"
    )


def downgrade() -> None:
    op.execute(sa.text(_data_refusal_sql()))

    op.drop_table("installation_state")
    op.drop_index(
        "ix_installation_manifest_validations_revision_id",
        table_name="installation_manifest_validations",
    )
    op.drop_table("installation_manifest_validations")
    op.drop_index(
        "ix_installation_manifest_revisions_predecessor_id",
        table_name="installation_manifest_revisions",
    )
    op.drop_table("installation_manifest_revisions")
    op.drop_index("ix_persona_versions_persona_id", table_name="persona_versions")
    op.drop_table("persona_versions")
    op.execute("DROP FUNCTION reject_immutable_installation_write()")
