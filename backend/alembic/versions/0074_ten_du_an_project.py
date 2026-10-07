"""Add the "Ten Du An" catch-all project and map the live ads that match no dự án.

Meta ships no ``utm_*`` on a Messenger ad, and the ads currently running set no
``ref`` either — their ``ads_context_data.ad_title`` is Meta's asset name
("album_xanh", "albumtuổiHOTLINE_VÀNG", "video 1"), which names no project. So
``resolve_project_from_attribution`` resolves only the ads an operator has
curated into a project's aliases (0073 maps the LG-DISPLAY one). Everything else
resolved to nothing and the digest printed a bare ad id.

Rather than leaving the recruiter with raw Meta ids, this creates the catch-all
project the owner asked for — "Ten Du An" (Dự án Mười) — and maps the ads that
are live today to it. ``resolve_project_from_attribution`` resolves them
through the same alias lookup as any other code, so they need no special case.

Idempotent and non-destructive, in the same way as 0073:

* the project is inserted only when its slug is absent, so an operator who
  renamed or edited it keeps theirs;
* each ad id is appended only when missing, so a replay cannot duplicate it and
  an operator's own aliases are never overwritten;
* downgrade removes only these ad ids, leaving the project and any real alias
  intact — deleting a project that may have gained a knowledge base would be
  destructive.

A FUTURE ad that matches nothing still prints its own id in the digest's
"Dự án quan tâm" column: that id is what an operator needs to map it, and
silently filing it here would hide that it is unmapped.

Revision ID: 0074_ten_du_an_project
Revises: 0073_map_lgd_messenger_ad
"""

from alembic import op

revision = "0074_ten_du_an_project"
down_revision = "0073_map_lgd_messenger_ad"
branch_labels = None
depends_on = None

PROJECT_SLUG = "du-an-muoi"
PROJECT_NAME = "Ten Du An"
PROJECT_ALIASES = ("Dự án Mười", "Dự án 10")

# Every Messenger ad observed in production that resolves to no other project.
MESSENGER_AD_IDS = (
    "120255327713950496",
    "120255221579150496",
    "120255206846290496",
    "120254725535810496",
    "120255327713900496",
)

_ALIASES_SQL = ", ".join(
    f"'{value.replace(chr(39), chr(39) * 2)}'" for value in PROJECT_ALIASES
)
_AD_IDS_SQL = ", ".join(f"'{value}'" for value in MESSENGER_AD_IDS)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO public.projects (slug, name, aliases, is_active)
        SELECT '{PROJECT_SLUG}', '{PROJECT_NAME}',
               ARRAY[{_ALIASES_SQL}]::text[], true
        WHERE NOT EXISTS (
            SELECT 1 FROM public.projects WHERE slug = '{PROJECT_SLUG}'
        )
        """
    )
    # Append only the ids this project does not already carry. The existing aliases
    # are read in a CTE because PostgreSQL will not let an UPDATE's target be
    # referenced from its own subquery; `missing.ids <> '{}'` skips the write
    # entirely when there is nothing new to add.
    op.execute(
        f"""
        WITH current AS (
            SELECT id, COALESCE(aliases, ARRAY[]::text[]) AS aliases
            FROM public.projects
            WHERE slug = '{PROJECT_SLUG}'
        ),
        missing AS (
            SELECT c.id,
                   COALESCE(array_agg(t.ad_id), ARRAY[]::text[]) AS ids
            FROM current c
            CROSS JOIN LATERAL unnest(ARRAY[{_AD_IDS_SQL}]::text[]) AS t(ad_id)
            WHERE NOT (c.aliases @> ARRAY[t.ad_id])
            GROUP BY c.id
        )
        UPDATE public.projects AS p
        SET aliases = c.aliases || m.ids, updated_at = now()
        FROM current AS c
        JOIN missing AS m ON m.id = c.id
        WHERE p.id = c.id AND m.ids <> ARRAY[]::text[]
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE public.projects
        SET aliases = (
                SELECT COALESCE(array_agg(value), ARRAY[]::text[])
                FROM unnest(COALESCE(aliases, ARRAY[]::text[])) AS value
                WHERE value <> ALL(ARRAY[{_AD_IDS_SQL}]::text[])
            ),
            updated_at = now()
        WHERE slug = '{PROJECT_SLUG}'
        """
    )