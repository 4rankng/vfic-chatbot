"""Map the three live album-tuổi Messenger ads to LG Display.

Same shape as 0073: Meta's Click-to-Messenger ads carry no ``utm_*`` and set
no ``ref``, and their ``ad_title`` is Meta's asset name ("albumtuổi_xanh",
"albumtuổiHOTLINE_VÀNG"), which names no project. The operator confirmed
these three ad ids belong to the LG Display campaign, so each id is curated
into ``lg-display.aliases`` — the catalog ``ad_id`` resolution
(``resolve_project_from_attribution``) then stamps the lead's dự án on the
first click. Additive and idempotent; never overwrites an operator alias.

Still unmapped after this (owner has not confirmed the projects):
120255327713900496, 120255434358460496, 120255452107110496,
120255434678730496, 120255447896930496, 120254725535810496.

Revision ID: 0074_map_lg_ads_album_tuoi
Revises: 0073_map_lgd_messenger_ad
"""

from alembic import op

revision = "0074_map_lg_ads_album_tuoi"
down_revision = "0073_map_lgd_messenger_ad"
branch_labels = None
depends_on = None

PROJECT_SLUG = "lg-display"
MESSENGER_AD_IDS = (
    "120255327713950496",
    "120255221579150496",
    "120255206846290496",
)


def upgrade() -> None:
    for ad_id in MESSENGER_AD_IDS:
        op.execute(
            f"""
            UPDATE public.projects
            SET aliases = array_append(aliases, '{ad_id}'), updated_at = now()
            WHERE slug = '{PROJECT_SLUG}'
              AND NOT (COALESCE(aliases, ARRAY[]::text[]) @> ARRAY['{ad_id}'])
            """
        )


def downgrade() -> None:
    for ad_id in MESSENGER_AD_IDS:
        op.execute(
            f"""
            UPDATE public.projects
            SET aliases = array_remove(aliases, '{ad_id}'), updated_at = now()
            WHERE slug = '{PROJECT_SLUG}'
              AND COALESCE(aliases, ARRAY[]::text[]) @> ARRAY['{ad_id}']
            """
        )
