"""Public contact and channel identity contracts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ChannelIdentityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,31}$")
    account_key: str = Field(min_length=1, max_length=128)
    external_id: str = Field(min_length=1, max_length=256)


class ChannelIdentityOut(ChannelIdentityCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    contact_id: uuid.UUID
    created_at: datetime


class ChannelIdentitySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    provider: str
    account_key: str
    external_id: str


class ContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=160)
    primary_email: EmailStr | None = Field(default=None, max_length=254)
    primary_phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=2000)
    locale: str | None = Field(default=None, max_length=35)
    channel_identities: list[ChannelIdentityCreate] = Field(default_factory=list, max_length=20)


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    display_name: str | None = Field(default=None, max_length=160)
    primary_email: EmailStr | None = Field(default=None, max_length=254)
    primary_phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=2000)
    locale: str | None = Field(default=None, max_length=35)


class ContactSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    display_name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    avatar_url: str | None = None
    primary_channel: ChannelIdentitySummaryOut | None = None


class ContactOut(ContactSummaryOut):
    version: int
    locale: str | None = None
    channel_identities: list[ChannelIdentityOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ContactListResponse(BaseModel):
    data: list[ContactOut]
    total: int
