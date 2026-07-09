"""Schemas for admin-managed integrations."""

from pydantic import BaseModel, ConfigDict, Field


class SecretStatus(BaseModel):
    configured: bool
    preview: str | None = None


class PlainStatus(BaseModel):
    configured: bool
    value: str | None = None


class ZaloOaSignatureHealth(BaseModel):
    """Passive result of the last real inbound OA webhook signature check.

    Surfaced on the integration status so a wrong OA Secret Key is visible the
    moment Zalo sends a real signed event, without clicking Test — the live Test
    probe authenticates with the access_token and cannot detect a wrong secret.
    """

    last_status: str | None = None  # "verified" | "mismatched"
    last_ts: float | None = None
    last_mismatch_ts: float | None = None
    consec_failures: int | None = None


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
    """

    configured: bool
    connected: bool = False
    missing: list[str]
    errors: list[str] = Field(default_factory=list)


class ZaloOaSignatureVerifyRequest(BaseModel):
    """A captured Zalo OA webhook event to verify against the stored OA Secret Key."""

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
