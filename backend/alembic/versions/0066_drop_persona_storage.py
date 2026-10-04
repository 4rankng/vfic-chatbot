"""drop persona storage — the persona is a code constant

Removes every database home the bot's persona had. ``app.prompts.vfic_persona``
is now the only persona, so a persona edit is a code change and a deploy and no
lane can drift onto a different voice.

Three persona tables go (``personas``, ``persona_versions``,
``adapter_persona_assignments``) plus the ``persona_version_id`` pin on
``installation_manifest_revisions``. The manifest keeps its fail-closed persona
checksum — it is now ``sha256_json({"body_md": AGENT_SYSTEM_PROMPT})``, a hash of
the deployed code rather than a snapshot row, so shipping a persona edit without
re-validating the manifest still invalidates it.

Drop order is forced by the foreign keys and is NOT interchangeable:
``installation_manifest_revisions.persona_version_id`` (RESTRICT) → the
adapter-assignment child (CASCADE) → ``persona_versions`` (RESTRICT, and
append-only behind a trigger) → ``personas``. Deliberately no ``CASCADE``: the
graph is known and enumerated, and a cascade would silently take anything else
that had grown a reference since.

``downgrade()`` recreates the whole pre-0066 schema rather than the
``FORWARD_ONLY: pass`` used by ``0010_drop_dead_schema_objects``. That precedent
is not available here: ``tests/integration/test_installation_migration_roundtrip.py``
downgrades to 0041, asserts ``persona_versions`` is absent, upgrades to head, and
asserts it is back. Reversibility is load-bearing for both CI and the deploy
rollback path.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0066_drop_persona_storage"
down_revision = "0065_geo_gazetteer"
branch_labels = None
depends_on = None

# The default 0020 installed on personas.followup_rules, recovered so the
# downgrade reproduces the exact pre-0066 column rather than an approximation.
_DEFAULT_FOLLOWUP_RULES = (
    '{"hot": {"enabled": true, "cadence_hours": [10, 22, 46], '
    '"eligible_stages": ["NEW"]}, '
    '"warm": {"enabled": true, "cadence_hours": [22, 46], '
    '"eligible_stages": ["NEW"]}, '
    '"not_interested": {"enabled": true, "cadence_hours": [46], '
    '"eligible_stages": ["NEW"]}}'
)


def upgrade() -> None:
    # 1. The manifest's persona pin. Its RESTRICT FK is what blocks the
    #    persona_versions drop, so it has to go first.
    op.drop_column("installation_manifest_revisions", "persona_version_id", schema="public")

    # 2. The provider-override child of `personas` (ON DELETE CASCADE).
    op.execute(
        "DROP TRIGGER IF EXISTS adapter_persona_assignments_touch "
        "ON public.adapter_persona_assignments"
    )
    op.drop_index(
        "ix_adapter_persona_assignments_persona",
        table_name="adapter_persona_assignments",
        schema="public",
    )
    op.drop_table("adapter_persona_assignments", schema="public")

    # 3. persona_versions: append-only behind a trigger, so the trigger goes
    #    before the table or a TRUNCATE/DROP path can trip it.
    op.execute("DROP TRIGGER IF EXISTS persona_versions_immutable ON public.persona_versions")
    op.drop_index("ix_persona_versions_persona_id", table_name="persona_versions", schema="public")
    op.drop_table("persona_versions", schema="public")

    # 4. personas. Its indexes, the knowledge_base FK and the touch trigger all
    #    belong to the table and go with it.
    op.execute("DROP TRIGGER IF EXISTS personas_touch ON public.personas")
    op.drop_index("ix_personas_knowledge_base", table_name="personas", schema="public")
    op.drop_index("personas_one_active", table_name="personas", schema="public")
    op.drop_index("personas_slug_key", table_name="personas", schema="public")
    op.drop_table("personas", schema="public")


def downgrade() -> None:
    # Recreated in the reverse of the order upgrade() drops them, so the
    # foreign keys are satisfied at every point rather than only at the end.
    op.create_table(
        "personas",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column(
            "followup_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT_FOLLOWUP_RULES}'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        # Named exactly as 0046 created it: 0046's own upgrade/downgrade
        # references this constraint by name, so a downgrade that recreates
        # `personas` with an auto-generated name breaks 0046 on the way back.
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name="fk_personas_knowledge_base",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index("personas_slug_key", "personas", ["slug"], unique=True, schema="public")
    # 0049 collapsed personas_one_active_global into a single partial index.
    op.execute("CREATE UNIQUE INDEX personas_one_active ON public.personas ((1)) WHERE is_active")
    op.create_index(
        "ix_personas_knowledge_base", "personas", ["knowledge_base_id"], schema="public"
    )
    op.execute(
        "CREATE TRIGGER personas_touch BEFORE UPDATE ON public.personas "
        "FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at()"
    )

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
        schema="public",
    )
    op.create_index(
        "ix_persona_versions_persona_id", "persona_versions", ["persona_id"], schema="public"
    )
    op.execute(
        """
        CREATE TRIGGER persona_versions_immutable
          BEFORE UPDATE OR DELETE ON persona_versions
          FOR EACH ROW EXECUTE FUNCTION reject_immutable_installation_write('created_by')
        """
    )

    op.create_table(
        "adapter_persona_assignments",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=False),
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
            "provider IN ('zalo_bot', 'zalo_oa', 'facebook_messenger')",
            name="adapter_persona_assignments_provider_valid",
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provider"),
        schema="public",
    )
    op.create_index(
        "ix_adapter_persona_assignments_persona",
        "adapter_persona_assignments",
        ["persona_id"],
        schema="public",
    )
    op.execute(
        """
        CREATE TRIGGER adapter_persona_assignments_touch
          BEFORE UPDATE ON public.adapter_persona_assignments
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at()
        """
    )

    # Restored last: it references persona_versions, which must already exist.
    # The original was an unnamed ForeignKeyConstraint inside create_table, so it
    # carried Postgres' auto name
    # (installation_manifest_revisions_persona_version_id_fkey). Nothing
    # references that name, so the explicit one below is equivalent — but the
    # column is restored NOT NULL, which is only satisfiable because the manifest
    # tables are empty in every deployment this has run against. A downgrade into
    # a database holding manifest revisions needs a persona_versions row first.
    op.add_column(
        "installation_manifest_revisions",
        sa.Column("persona_version_id", sa.UUID(), nullable=False),
        schema="public",
    )
    op.create_foreign_key(
        "fk_installation_manifest_revisions_persona_version",
        "installation_manifest_revisions",
        "persona_versions",
        ["persona_version_id"],
        ["id"],
        ondelete="RESTRICT",
        # create_foreign_key takes source_schema/referent_schema; a bare `schema`
        # is forwarded to the dialect and raises.
        source_schema="public",
        referent_schema="public",
    )
