"""Persist human-verified places the geocoders cannot be trusted to find.

A curated gazetteer. Every provider studied on 2026-10-03 failed to place at
least one site this bot serves: KCN Nomura is in no provider's index, and KCN
VSIP comes back with two readings 4 km apart depending on whether the company
name is in the query. A recruiter knows where their own plant is. This table is
where that knowledge is recorded once, so resolution costs no API call and
cannot drift with a provider's index.

A row here is authoritative: :mod:`app.services.geo.factory_point` consults it
BEFORE any provider and returns its coordinates directly, skipping both the
geocoding hops and the reverse-verification lookup. The trade is explicit — a
human can be wrong, and a wrong row is served forever — so the table records
where the coordinate came from (``source``) and who verified it
(``verified_by``), and is only consulted when the address actually names the
place.

Matching is token-subset, not fuzzy: an entry (or one of its aliases) matches
an address component when the entry's normalized words all appear in that
component's. "KCN Tràng Duệ" therefore matches "Công ty 4P, KCN Tràng Duệ,
An Phong" and cannot match "An Dương", which is the discrimination that keeps
a gazetteer from answering the wrong question.

Additive: no existing table changes.

Revision ID: 0065_geo_gazetteer
Revises: 0064_geocode_place_check
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "0065_geo_gazetteer"
down_revision = "0064_geocode_place_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_gazetteer",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        # Comma-separated alternative names, e.g. "KCN Nhật Bản,Nomura,NHIZ".
        # Matched the same way as `name`; one hit is enough.
        sa.Column("aliases", sa.Text(), nullable=False, server_default=text("''")),
        sa.Column("province", sa.Text(), nullable=True),
        sa.Column("district", sa.Text(), nullable=True),
        sa.Column("ward", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        # Where the coordinate came from — "osm", "google", a recruiter's own
        # map pin. Provenance, not decoration: a row is served forever, so it
        # has to be possible to say why it is trusted.
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        # Unique so the seed is idempotent and an upsert has something to
        # conflict on: one row per place, re-runnable without duplicating it.
        sa.UniqueConstraint("name", name="ux_geo_gazetteer_name"),
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
    )


def downgrade() -> None:
    op.drop_table("geo_gazetteer")
