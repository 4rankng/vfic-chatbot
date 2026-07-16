"""Read-only contact summaries embedded in conversation responses."""

import uuid
from pydantic import BaseModel, ConfigDict


class ChannelIdentitySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    provider: str
    account_key: str
    external_id: str


class ContactSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    display_name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    avatar_url: str | None = None
    primary_channel: ChannelIdentitySummaryOut | None = None
