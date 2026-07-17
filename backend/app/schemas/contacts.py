"""Read-only contact summaries embedded in conversation responses.

Privacy contract (Alembic 0047 / Phase 2): raw external participant identifiers
(Messenger PSID, Zalo chat id, OA user id) and raw account keys (Facebook Page
id) never reach the recruiter API. They are masked at the schema boundary here
via field validators. The backend's ``participant_display_id`` (on
ConversationOut) is the canonical masked projection; these nested summaries
expose the same masked form so a stray serialization cannot leak PII.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator


def _mask_identifier(value: str | None) -> str | None:
    """Mask all but the last 4 chars; short values collapse to a fixed mask."""
    if value is None:
        return None
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


class ChannelIdentitySummaryOut(BaseModel):
    """Neutral channel-identity summary with masked external identifiers.

    ``external_id`` and ``account_key`` are masked at validation time, so the
    raw ORM values never survive into a serialized response. ``provider`` is
    safe to expose (it is a canonical id like ``zalo_bot`` /
    ``facebook_messenger``, not a user id).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    account_key: str | None = None
    external_id: str | None = None

    @field_validator("account_key", "external_id", mode="before")
    @classmethod
    def _mask(cls, v: str | None) -> str | None:
        return _mask_identifier(v)


class ContactSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    avatar_url: str | None = None
    primary_channel: ChannelIdentitySummaryOut | None = None
