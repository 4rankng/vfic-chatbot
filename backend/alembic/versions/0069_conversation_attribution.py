"""conversations.attribution — the first-touch source of a candidate thread.

Additive: one nullable JSONB column, no existing row is touched, so blue and
green run against either schema. ``downgrade()`` drops it; only the inbound
path writes it and only new conversations would ever get it back.

Shape (flat, so SQL can filter on ``attribution->>'ad_id'``):
    {"kind": "post_link" | "referral",
     "post_code": "<our code — Zalo #CODE prefill / Meta ref>",
     "ad_id": "<Meta ad id>",
     "post_id": "<Meta ads_context_data.post_id>",
     "referral_source": "ADS" | "SHORTLINK"}
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0069_conversation_attribution"
down_revision = "0068_push_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "attribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "attribution")
