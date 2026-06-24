"""User request/response schemas.

Emails are normalised to lowercase on write; the DB unique index is on lower(email).
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import Role


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None
    role: Role = Role.recruiter
    disabled: bool = False


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    role: Role | None = None
    disabled: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    disabled: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    """Envelope shape consumed by the frontend REST dataProvider (US-010)."""

    data: list[UserOut]
    total: int
