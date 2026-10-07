"""Map the live LG-DISPLAY Click-to-Messenger ad to its project.

Meta ships no ``utm_*`` on a Messenger ad, and the ads running today set no
``ref`` either — their ``ads_context_data.ad_title`` is the asset name
("album_xanh"), which names no project. So ``resolve_project_from_attribution``
could not map them and every Messenger candidate fell back to the Page's
ambiguous project list ("LG Electronics, LG-DISPLAY") even though the system
knew exactly which ad they clicked.

``resolve_project_from_attribution`` now resolves ``ad_id`` against the project
catalog alongside ``ref``, so the mapping lives where every other
operator-curated code lives: ``projects.aliases``. Adding the ad id there is
additive and idempotent — it can never overwrite an operator's own alias — and
a fresh deployment gets the same mapping from this file.

Downgrade removes only this alias, and only the one this migration added, so a
project's real aliases survive a downgrade/upgrade cycle.

Revision ID: 0073_map_lgd_messenger_ad
Revises: 0072_tingting_hotline_number
"""

from alembic import op

revision = "0073_map_lgd_messenger_ad"
down_revision = "0072_tingting_hotline_number"
branch_labels = None
depends_on = None

PROJECT_SLUG = "lg-display"
MESSENGER_AD_ID = "120255397858310496"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE public.projects
        SET aliases = array_append(aliases, '{MESSENGER_AD_ID}'), updated_at = now()
        WHERE slug = '{PROJECT_SLUG}'
          AND NOT (COALESCE(aliases, ARRAY[]::text[]) @> ARRAY['{MESSENGER_AD_ID}'])
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE public.projects
        SET aliases = array_remove(aliases, '{MESSENGER_AD_ID}'), updated_at = now()
        WHERE slug = '{PROJECT_SLUG}'
          AND COALESCE(aliases, ARRAY[]::text[]) @> ARRAY['{MESSENGER_AD_ID}']
        """
    )