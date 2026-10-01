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

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


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

    ``display_channel`` is derived from the raw ``account_key`` BEFORE masking
    (the masked value can no longer tell the TingTing employee-support OA from
    the other ``zalo_oa`` account). It mirrors the channel vocabulary the
    frontend row chips render: ``tingting_oa`` for the support account, the
    raw provider for everything else. The ``"tingting"`` literal duplicates
    ``app/channels/types.py::TINGTING_OA_ACCOUNT_KEY`` because the schemas
    layer cannot import the channels layer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    account_key: str | None = None
    external_id: str | None = None
    display_channel: str | None = None

    @field_validator("account_key", "external_id", mode="before")
    @classmethod
    def _mask(cls, v: str | None) -> str | None:
        return _mask_identifier(v)

    @model_validator(mode="before")
    @classmethod
    def _derive_display_channel(cls, data):
        if isinstance(data, dict):
            provider = data.get("provider")
            raw_account_key = data.get("account_key")
        else:
            provider = getattr(data, "provider", None)
            raw_account_key = getattr(data, "account_key", None)
        if provider == "zalo_oa" and raw_account_key == "tingting":
            display_channel = "tingting_oa"
        elif provider:
            display_channel = provider
        else:
            display_channel = None
        if isinstance(data, dict):
            return {**data, "display_channel": display_channel}
        # from_attributes path: project the needed columns into a dict so the
        # raw account_key flows through masking untouched.
        return {
            "id": getattr(data, "id", None),
            "provider": provider,
            "account_key": raw_account_key,
            "external_id": getattr(data, "external_id", None),
            "display_channel": display_channel,
        }


class ContactSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    avatar_url: str | None = None
    primary_channel: ChannelIdentitySummaryOut | None = None
