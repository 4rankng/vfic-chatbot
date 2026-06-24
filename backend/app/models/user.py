"""User model (replaces Supabase `profiles` + `auth.users`)."""
import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(str, enum.Enum):
    admin = "admin"
    recruiter = "recruiter"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="app_role", create_type=False),
        nullable=False,
        default=Role.recruiter,
        server_default="recruiter",
    )
    disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.text("false")
    )
    # Bumped on password change (and future credential resets) so every
    # previously-issued JWT (carrying the old `ver` claim) is rejected at the
    # auth gate. Revocation without a server-side denylist.
    token_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),  # DB trigger touch_updated_at() also refreshes this
    )
