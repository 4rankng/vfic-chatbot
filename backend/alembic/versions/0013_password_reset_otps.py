"""Add password reset OTPs.

Revision ID: 0013_password_reset_otps
Revises: 0012_add_contact_info_feature
Create Date: 2026-06-29
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_password_reset_otps"
down_revision = "0012_add_contact_info_feature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.password_reset_otps (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          email         text NOT NULL,
          otp_hash      text NOT NULL,
          expires_at    timestamptz NOT NULL,
          consumed_at   timestamptz,
          attempt_count integer NOT NULL DEFAULT 0,
          created_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX password_reset_otps_user_idx
          ON public.password_reset_otps (user_id, created_at DESC);
        CREATE INDEX password_reset_otps_email_active_idx
          ON public.password_reset_otps (lower(email), expires_at DESC)
          WHERE consumed_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE public.password_reset_otps")
