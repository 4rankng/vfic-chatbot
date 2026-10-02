"""Persist a durable geocoder query→coordinates mapping.

``geocode_cache`` stores one row per distinct normalized geocoder query: the
resolved coordinates plus which provider resolved them, or a NULL-coordinate
row recording a miss. The lookup consults this table before any provider HTTP
call (Redis stays in front of it as the fast, expiring copy); miss rows expire
by ``updated_at`` so improving provider coverage is picked up, while positive
rows persist. Additive: no existing table changes.

Revision ID: 0062_geocode_cache
Revises: 0061_project_coordinates
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0062_geocode_cache"
down_revision = "0061_project_coordinates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geocode_cache",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
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
        sa.UniqueConstraint("query", name="ux_geocode_cache_query"),
    )


def downgrade() -> None:
    op.drop_table("geocode_cache")
