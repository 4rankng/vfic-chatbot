"""Persist road-distance estimates per geocoded coordinate pair.

``distance_estimate`` stores one row per distinct origin → destination point
pair: the road estimate (km, optional travel seconds) from the matrix
providers and which provider produced it. The catalog tools consult this
table before any matrix HTTP call, so one pair is estimated once and served
from the database afterwards.

Keys are rounded coordinates (5 dp ≈ 1.1 m), not raw address strings: the
origin always arrives geocoded, so the same stated address collapses to the
same row, and a re-geocoded project point simply misses and re-estimates.
Only successful estimates are stored — a provider outage writes nothing and
the next turn retries. Additive: no existing table changes.

Revision ID: 0063_distance_estimate
Revises: 0062_geocode_cache
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0063_distance_estimate"
down_revision = "0062_geocode_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "distance_estimate",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("origin_key", sa.Text(), nullable=False),
        sa.Column("destination_key", sa.Text(), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=True),
        # "vietmap" | "google" — the matrix provider that produced the row.
        sa.Column("provider", sa.String(length=32), nullable=False),
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
        sa.UniqueConstraint(
            "origin_key", "destination_key", name="ux_distance_estimate_pair"
        ),
    )


def downgrade() -> None:
    op.drop_table("distance_estimate")
