"""worker_feature_catalog.is_active — trim the catalog to manual-labour scope.

VFIC recruits manual labourers (công nhân thời vụ), so 5 of the original 16 worker
product features (migration 0004) are out of scope: ``trust_signal`` (a meta-judgment
about the posting, not an extracted product attribute), ``contract_security``,
``health_safety``, ``work_life_balance`` and ``career_growth`` (white-collar concepts a
temp labourer doesn't ask about). The canonical posting (kb/LGDisplay/LGDisplay.txt)
answers the other 11 and is silent on these 5.

Rather than delete the rows (destructive, loses already-extracted ``job_feature_values``
and is irreversible), this adds a soft ``is_active`` flag and disables the 5. The flag is
honoured by ``JobFeatureValueRepo.fetch_catalog`` (drives the extraction prompt + the
one-row-per-feature write) and by the feature-list / readiness read paths, so disabled
features drop out of extraction, the agent tool, and the readiness gauge automatically.
Reversible: flip the flag to revive a criterion if VFIC ever staffs a non-manual role.

Revision ID: 0009_feature_catalog_active
Revises: 0008_drop_bus_timetable_fn
Create Date: 2026-06-28
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_feature_catalog_active"
down_revision = "0008_drop_bus_timetable_fn"
branch_labels = None
depends_on = None

# Manual-labour-out-of-scope criteria (see kb/LGDisplay/LGDisplay.txt). Inlined as a SQL
# literal to match the codebase migration style; this is a point-in-time data migration.
_INACTIVE_KEYS_SQL = "('trust_signal', 'contract_security', 'health_safety', 'work_life_balance', 'career_growth')"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.worker_feature_catalog
          ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;
        """
    )
    op.execute(
        f"UPDATE public.worker_feature_catalog SET is_active = false "
        f"WHERE feature_key IN {_INACTIVE_KEYS_SQL};"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS worker_feature_catalog_active_idx "
        "ON public.worker_feature_catalog (is_active);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.worker_feature_catalog_active_idx;")
    op.execute("ALTER TABLE public.worker_feature_catalog DROP COLUMN IF EXISTS is_active;")
