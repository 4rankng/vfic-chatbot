"""Schemas for admin-managed integrations."""
from pydantic import BaseModel, ConfigDict, Field


class SecretStatus(BaseModel):
    configured: bool
    preview: str | None = None


class PlainStatus(BaseModel):
    configured: bool
    value: str | None = None


class ZaloIntegrationSettingsOut(BaseModel):
    zalo_bot_token: SecretStatus
    zalo_bot_webhook_secret: SecretStatus
    zalo_oa_app_id: PlainStatus
    zalo_oa_secret_key: SecretStatus
    zalo_oa_access_token: SecretStatus
    zalo_bot_api_base: str
    zalo_oa_api_base: str


class ZaloIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zalo_bot_token: str | None = Field(default=None, min_length=1, max_length=2048)
    zalo_bot_webhook_secret: str | None = Field(default=None, min_length=8, max_length=256)
    zalo_oa_app_id: str | None = Field(default=None, min_length=1, max_length=128)
    zalo_oa_secret_key: str | None = Field(default=None, min_length=1, max_length=2048)
    zalo_oa_access_token: str | None = Field(default=None, min_length=1, max_length=4096)


class ZaloIntegrationTestOut(BaseModel):
    bot_configured: bool
    oa_configured: bool
    missing: list[str]
