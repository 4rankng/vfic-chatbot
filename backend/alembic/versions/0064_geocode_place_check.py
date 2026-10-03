"""Persist the reverse-geocoded place names of a coordinate.

A factory's work address is only trustworthy when the point a geocoder returns
actually sits in the place the address itself names. Verifying that needs a
reverse lookup, and Nominatim's usage policy caps it at one request per second —
so during a backfill every project would pay a second per candidate. Caching the
answer per coordinate makes the check a once-per-point cost forever.

``geocode_place_check`` stores, per coordinate, the normalized place names the
reverse lookup reported (the ``industrial``/``suburb``/``quarter``/``road``/
``city`` fields, diacritics stripped, **one name per line**). The line boundary
is load-bearing: a containment check asks whether an anchor's words all appear
inside ONE reported name, so a space-joined bag of words would make every
multi-word anchor unmatchable on the next read. The containment decision itself
is always recomputed against the current address — only the network result is
durable, because which names matter is a property of the address, not of the
coordinate.

Keys are coordinates rounded to 5 dp (≈ 1.1 m) for the same reason
``distance_estimate`` does: a provider returning the same facility twice
collapses to one row. Additive: no existing table changes.

Revision ID: 0064_geocode_place_check
Revises: 0063_distance_estimate
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0064_geocode_place_check"
down_revision = "0063_distance_estimate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geocode_place_check",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # "lat,lng" at 5 dp — see the module docstring.
        sa.Column("coord_key", sa.Text(), nullable=False),
        # Newline-joined, diacritic-stripped, lowercased place names, one per
        # line — see the module docstring for why the line boundary matters.
        # A row is written only for a successful lookup, so its presence means
        # "verified once"; an empty string is a real answer ("nothing here but
        # open road").
        sa.Column("place_names", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("coord_key", name="ux_geocode_place_check_coord"),
    )


def downgrade() -> None:
    op.drop_table("geocode_place_check")
