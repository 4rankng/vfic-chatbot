"""Seed the support OA's escalation hotline (operator rule 2026-09-29).

The TingTing support OA has no human queue: whenever the bot cannot help
in-chat it points the employee at the escalation hotline. That number is an
admin-editable integration setting (``tingting_hotline``), read at turn time —
the owner approved +84 914 827 988 as the initial value, so it is seeded here
instead of kept as a code fallback that would drift from the admin-edited
value.

The row is stored PLAINTEXT in the settings value column with ``is_secret =
false``: the cipher fails soft on rows without the ``v1:`` prefix (a
documented contract for manual/seeded rows), so the seeded number and a later
admin-encrypted edit both read back through the same getter. The WHERE guard
makes the seed idempotent and operator edits win over it — re-running or
replaying the migration never overwrites an admin change.

Downgrade removes the row only when it still holds the seeded value, so an
operator-edited hotline survives a downgrade/upgrade cycle.

Revision ID: 0058_tingting_hotline_setting
Revises: 0057_drop_match_memories_vector_overload
"""

from alembic import op

revision = "0058_tingting_hotline_setting"
down_revision = "0057_drop_match_memories_vector_overload"
branch_labels = None
depends_on = None

SEED_VALUE = "+84 914 827 988"


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO public.integration_settings (key, encrypted_value, is_secret)
        SELECT 'tingting_hotline', '+84 914 827 988', false
        WHERE NOT EXISTS (
            SELECT 1 FROM public.integration_settings WHERE key = 'tingting_hotline'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM public.integration_settings
        WHERE key = 'tingting_hotline' AND encrypted_value = '{SEED_VALUE}'
        """
    )
