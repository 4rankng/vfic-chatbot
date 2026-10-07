"""Correct the support OA's escalation hotline to the owner's current number.

Alembic 0058 seeded ``+84 914 827 988`` when the owner approved it at the time.
The owner has since corrected the escalation hotline to ``02256548788`` — the
support OA's Hải Phòng landline rather than a mobile — so the seeded value is
carried forward here instead of by editing 0058, which has already been applied
in every environment and whose value is a historical record of what was
approved then.

This stays a SETTING migration, not a code fallback: the runtime still reads
only ``tingting_hotline`` (``services/tingting_api.py::hotline``), re-read every
turn so an admin edit still takes effect on the next message without a deploy.
Nothing in the runtime copy hardcodes the number.

Same guard contract as 0058, so operator edits keep winning:

* **upgrade** updates only a row that still holds the superseded seed, and
  inserts only when the row is absent. An admin-encrypted row (``v1:``-prefixed,
  as ``replace_hotline`` writes) does not match either guard and is left alone.
* **downgrade** restores the superseded value only when the row still holds the
  value this migration wrote, so an operator who edits it afterwards keeps their
  number through a downgrade/upgrade cycle.

Revision ID: 0072_tingting_hotline_number
Revises: 0071_lead_project_id
"""

from alembic import op

revision = "0072_tingting_hotline_number"
down_revision = "0071_lead_project_id"
branch_labels = None
depends_on = None

# What 0058 seeded, and the owner's current escalation hotline.
PREVIOUS_VALUE = "+84 914 827 988"
HOTLINE_VALUE = "02256548788"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE public.integration_settings
        SET encrypted_value = '{HOTLINE_VALUE}', updated_at = now()
        WHERE key = 'tingting_hotline' AND encrypted_value = '{PREVIOUS_VALUE}'
        """
    )
    # A deployment that never ran 0058's seed (or cleared the row) gets the
    # current number rather than being left with none; the guard still yields to
    # any row that already holds a value.
    op.execute(
        f"""
        INSERT INTO public.integration_settings (key, encrypted_value, is_secret)
        SELECT 'tingting_hotline', '{HOTLINE_VALUE}', false
        WHERE NOT EXISTS (
            SELECT 1 FROM public.integration_settings WHERE key = 'tingting_hotline'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE public.integration_settings
        SET encrypted_value = '{PREVIOUS_VALUE}', updated_at = now()
        WHERE key = 'tingting_hotline' AND encrypted_value = '{HOTLINE_VALUE}'
        """
    )