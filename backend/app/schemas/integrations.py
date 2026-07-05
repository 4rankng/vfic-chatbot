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


class MinimaxIntegrationSettingsOut(BaseModel):
    minimax_api_key: SecretStatus
    minimax_base_url: str
    minimax_agent_model: str
    minimax_safety_model: str


class MinimaxIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimax_api_key: str | None = Field(default=None, min_length=1, max_length=4096)


class MinimaxIntegrationTestOut(BaseModel):
    configured: bool
    missing: list[str]


class OpenRouterIntegrationSettingsOut(BaseModel):
    openrouter_api_key: SecretStatus
    openrouter_base_url: str
    openrouter_agent_model: str
    openrouter_safety_model: str
    openrouter_digest_model: str
    openrouter_embedding_model: str
    openrouter_embedding_dim: int


class OpenRouterIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openrouter_api_key: str | None = Field(default=None, min_length=1, max_length=4096)


class OpenRouterIntegrationTestOut(BaseModel):
    configured: bool
    missing: list[str]
