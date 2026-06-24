"""Add users.token_version for JWT revocation on password change.

Each issued access/refresh token carries a ``ver`` claim equal to the user's
``token_version`` at issue time. ``change-password`` (and any future
credentials-changing action) bumps ``token_version``, so every previously-issued
token's ``ver`` no longer matches and is rejected at the auth gate — without
maintaining a server-side denylist.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-26
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.users ADD COLUMN token_version integer NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.users DROP COLUMN token_version")
