"""Web Push subscription contracts (see ``app/api/notifications.py``)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)
    keys: SubscriptionKeys
    user_agent: str | None = Field(default=None, max_length=300)


class SubscriptionOut(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)


class VapidKeyOut(BaseModel):
    enabled: bool
    key: str


class PushTestOut(BaseModel):
    sent: int
