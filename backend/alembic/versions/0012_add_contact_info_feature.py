"""Add contact_info to worker_feature_catalog.

Adds a 12th active worker-interest feature: "Thông tin liên lạc" — the contact
person and phone number candidates should reach when they need support. This is
an operational readiness signal (training-day contact), not a job-attribute
differentiator, so it sits at the low end of the importance axis (0.55).

The `## Contacts` section was already a required section in the canonical
KB format; this catalog row makes it visible in the per-project FeatureGauge
readiness gauge and the agent's get_product_features tool.

Revision ID: 0012_add_contact_info_feature
Revises: 0011_bus_search_null_slug
Create Date: 2026-06-29
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_add_contact_info_feature"
down_revision = "0011_bus_search_null_slug"
branch_labels = None
depends_on = None

_CONTACT_INFO_ROW = (
    "contact_info",
    "Thông tin liên lạc",
    "contact",
    "Liên hệ ai khi cần hỗ trợ?",
    0.55,
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO public.worker_feature_catalog
          (feature_key, name_vi, category, worker_question_vi, default_importance_score, is_active)
        VALUES
          ('contact_info', 'Thông tin liên lạc', 'contact', 'Liên hệ ai khi cần hỗ trợ?', 0.55, true)
        ON CONFLICT (feature_key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM public.worker_feature_catalog WHERE feature_key = 'contact_info';"
    )
