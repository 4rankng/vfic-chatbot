"""Schemas for admin-managed integrations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SecretStatus(BaseModel):
    configured: bool
    preview: str | None = None


class PlainStatus(BaseModel):
    configured: bool
    value: str | None = None


class ZaloOaSignatureHealth(BaseModel):
    """Passive result of the last real inbound OA webhook signature check.

    Surfaced on the integration status so a wrong Webhook Secret is visible the
    moment Zalo sends a real signed event, without clicking Test — the live Test
    probe authenticates with the access_token and cannot detect a wrong secret.
    """

    last_status: str | None = None  # "verified" | "mismatched"
    last_ts: float | None = None
    last_mismatch_ts: float | None = None
    consec_failures: int | None = None


class WebhookSyncStatus(BaseModel):
    """Outcome of pushing the saved Bot webhook secret to Zalo via setWebhook.

    Saving the webhook secret in the CRM updates only the app side; Zalo keeps
    sending the old secret_token until ``setWebhook`` re-registers it, and a
    mismatch silently 401-drops every inbound. This status makes that push
    explicit so a save either confirms the two sides now match, or surfaces why
    it could not (no URL configured, Zalo rejected it, etc.).
    """

    synced: bool
    url: str | None = None
    skipped: str | None = None
    error: str | None = None


class ZaloIntegrationSettingsOut(BaseModel):
    zalo_bot_token: SecretStatus
    zalo_bot_webhook_secret: SecretStatus
    zalo_oa_app_id: PlainStatus
    zalo_oa_secret_key: SecretStatus
    zalo_oa_access_token: SecretStatus
    zalo_oa_refresh_token: SecretStatus
    zalo_bot_api_base: str
    zalo_oa_api_base: str
    zalo_oa_webhook_signature: ZaloOaSignatureHealth | None = None
    # Only populated by PUT /zalo after a bot token/secret change; GET leaves it
    # unset (read-only, no push).
    zalo_bot_webhook_sync: WebhookSyncStatus | None = None


class ZaloIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zalo_bot_token: str | None = Field(default=None, min_length=1, max_length=2048)
    zalo_bot_webhook_secret: str | None = Field(default=None, min_length=8, max_length=256)
    zalo_oa_app_id: str | None = Field(default=None, min_length=1, max_length=128)
    zalo_oa_secret_key: str | None = Field(default=None, min_length=1, max_length=2048)
    zalo_oa_access_token: str | None = Field(default=None, min_length=1, max_length=4096)
    zalo_oa_refresh_token: str | None = Field(default=None, min_length=1, max_length=4096)


class ZaloChannelTestOut(BaseModel):
    """Result of probing ONE Zalo channel (Bot Platform or OA).

    The two channels are independent products with separate credentials, so each
    card's "Test Connection" button probes only its own channel rather than the
    old combined envelope that conflated both.

    ``webhook_registered``/``webhook_url`` apply only to the Bot channel (from
    ``getWebhookInfo``); they are ``None`` for the OA probe. Zalo never returns
    the registered secret_token, so a registered URL does not prove the secret
    matches — only a real inbound does.
    """

    configured: bool
    connected: bool = False
    missing: list[str]
    errors: list[str] = Field(default_factory=list)
    webhook_registered: bool | None = None
    webhook_url: str | None = None


class ZaloOaSignatureVerifyRequest(BaseModel):
    """A captured Zalo OA webhook event to verify against the stored Webhook Secret."""

    model_config = ConfigDict(extra="forbid")

    signature: str = Field(..., min_length=1, max_length=256)
    raw_body: str = Field(..., min_length=1, max_length=65536)
    timestamp: str = Field(default="", max_length=64)


class ZaloOaSignatureVerifyOut(BaseModel):
    verified: bool
    secret_configured: bool
    app_id_configured: bool
    matched_label: str | None = None
    detail: str


class MinimaxIntegrationSettingsOut(BaseModel):
    minimax_api_key: SecretStatus
    minimax_base_url: str
    minimax_agent_model: str
    minimax_safety_model: str
    minimax_enable: bool
    llm_default_provider: Literal["minimax", "openrouter"]


class MinimaxIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimax_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    minimax_enable: bool | None = None
    llm_default_provider: Literal["minimax", "openrouter"] | None = None


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
    openrouter_enable: bool
    llm_default_provider: Literal["minimax", "openrouter"]


class OpenRouterIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openrouter_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    openrouter_enable: bool | None = None
    openrouter_agent_model: str | None = Field(default=None, min_length=1, max_length=256)
    openrouter_safety_model: str | None = Field(default=None, min_length=1, max_length=256)
    openrouter_digest_model: str | None = Field(default=None, min_length=1, max_length=256)
    llm_default_provider: Literal["minimax", "openrouter"] | None = None


class OpenRouterIntegrationTestOut(BaseModel):
    configured: bool
    missing: list[str]
