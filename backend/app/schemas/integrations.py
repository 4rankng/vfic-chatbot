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

    OA-specific diagnostics (``oa_secret_valid``, ``oa_refresh_ok``,
    ``oa_token_expired``) are ``None`` for Bot probes.
    """

    configured: bool
    connected: bool = False
    missing: list[str]
    errors: list[str] = Field(default_factory=list)
    webhook_registered: bool | None = None
    webhook_url: str | None = None
    # OA-only diagnostics — None for Bot channel probes.
    oa_secret_valid: bool | None = None
    oa_refresh_ok: bool | None = None
    oa_token_expired: bool | None = None


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


class ProviderTestStatus(BaseModel):
    """Last real-probe outcome for one provider (persisted across reloads)."""

    ok: bool
    latency_ms: int | None = None
    tested_at: int
    error: str | None = None


class GeocoderIntegrationSettingsOut(BaseModel):
    google_maps_api_key: SecretStatus


class GeocoderIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    google_maps_api_key: str | None = Field(default=None, min_length=1, max_length=512)


class MinimaxIntegrationSettingsOut(BaseModel):
    minimax_api_key: SecretStatus
    minimax_base_url: str
    minimax_agent_model: str
    minimax_extractor_model: str
    minimax_enable: bool
    llm_default_provider: Literal["minimax", "openrouter", "custom"]
    llm_failover_order: list[Literal["minimax", "openrouter", "custom"]]
    llm_reasoning_mode: Literal["off", "low", "default"]
    llm_agent_max_tokens: int
    # Forward the first complete answer bubble before the agent finishes.
    llm_progressive_send: bool
    last_test: ProviderTestStatus | None = None


class MinimaxIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimax_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    minimax_enable: bool | None = None
    llm_default_provider: Literal["minimax", "openrouter", "custom"] | None = None
    # Operator-ranked spare order; like the default radio it rides the minimax
    # PUT only, so the other panels' Update models deliberately omit it.
    llm_failover_order: list[Literal["minimax", "openrouter", "custom"]] | None = None
    # Generic agent-lane decode knobs (stored on the minimax panel like the two
    # fields above). 0 tokens means "no cap".
    llm_reasoning_mode: Literal["off", "low", "default"] | None = None
    llm_agent_max_tokens: int | None = Field(default=None, ge=0)
    # Opt-in progressive delivery: stream the first answer bubble early.
    llm_progressive_send: bool | None = None


class MinimaxIntegrationTestOut(BaseModel):
    configured: bool
    missing: list[str]
    # Real-probe result fields (the probe replaced the old key-presence check).
    ok: bool = False
    latency_ms: int | None = None
    sample: str | None = None
    error: str | None = None


class OpenRouterIntegrationSettingsOut(BaseModel):
    openrouter_api_key: SecretStatus
    openrouter_base_url: str
    openrouter_agent_model: str
    openrouter_extractor_model: str
    openrouter_digest_model: str
    openrouter_embedding_model: str
    openrouter_embedding_dim: int
    openrouter_enable: bool
    llm_default_provider: Literal["minimax", "openrouter", "custom"]
    llm_failover_order: list[Literal["minimax", "openrouter", "custom"]]
    embedding_provider: Literal["openrouter", "gemini"]
    embedding_gemini_api_key: SecretStatus
    last_test: ProviderTestStatus | None = None


class OpenRouterIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openrouter_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    openrouter_enable: bool | None = None
    openrouter_agent_model: str | None = Field(default=None, min_length=1, max_length=256)
    openrouter_extractor_model: str | None = Field(default=None, min_length=1, max_length=256)
    openrouter_digest_model: str | None = Field(default=None, min_length=1, max_length=256)
    llm_default_provider: Literal["minimax", "openrouter", "custom"] | None = None
    embedding_provider: Literal["openrouter", "gemini"] | None = None
    embedding_gemini_api_key: str | None = Field(default=None, min_length=1, max_length=4096)


class OpenRouterIntegrationTestOut(BaseModel):
    configured: bool
    missing: list[str]
    ok: bool = False
    latency_ms: int | None = None
    sample: str | None = None
    error: str | None = None


# ─── Custom OpenAI-compatible provider ──────────────────────────────────────
# A third first-class provider (e.g. Xiaomi MiMo) supplied entirely by the
# operator: base URL + model ids + credential. It can be selected as the default
# like MiniMax or OpenRouter, and participates in quota failover either way.


class CustomLlmIntegrationSettingsOut(BaseModel):
    custom_llm_api_key: SecretStatus
    custom_llm_base_url: str
    custom_llm_agent_model: str
    custom_llm_fast_model: str
    custom_llm_label: str
    custom_llm_enable: bool
    # True only when enabled + key + base URL + agent model are all present,
    # so the UI can say "armed" rather than merely "saved".
    custom_llm_usable: bool
    llm_default_provider: Literal["minimax", "openrouter", "custom"]
    llm_failover_order: list[Literal["minimax", "openrouter", "custom"]]
    last_test: ProviderTestStatus | None = None


class CustomLlmIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    custom_llm_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    custom_llm_base_url: str | None = Field(default=None, min_length=1, max_length=512)
    custom_llm_agent_model: str | None = Field(default=None, min_length=1, max_length=256)
    custom_llm_fast_model: str | None = Field(default=None, min_length=1, max_length=256)
    custom_llm_label: str | None = Field(default=None, min_length=1, max_length=64)
    custom_llm_enable: bool | None = None
    llm_default_provider: Literal["minimax", "openrouter", "custom"] | None = None


class CustomLlmProbeIn(BaseModel):
    """Credentials to probe before they are saved.

    Any field left unset falls back to the stored value, so an operator can
    re-probe a saved provider without re-entering the key.
    """

    model_config = ConfigDict(extra="forbid")

    custom_llm_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    custom_llm_base_url: str | None = Field(default=None, min_length=1, max_length=512)
    custom_llm_agent_model: str | None = Field(default=None, min_length=1, max_length=256)


class CustomLlmIntegrationTestOut(BaseModel):
    """Result of a real chat call against the provider."""

    ok: bool
    configured: bool
    missing: list[str]
    # Round-trip latency and a short echo of the reply, so a green result is
    # evidence the endpoint actually answered rather than merely accepted TCP.
    latency_ms: int | None = None
    sample: str | None = None
    error: str | None = None


# ─── TypeSafe Jev (System One decision model) ───────────────────────────────
# Server-side decision hops for the bot turn: intent routing, sort direction,
# pleasantry kind, and conversation-context flags. One key + model pair, stored
# like every other integration secret (encrypted at rest, set from the admin UI).


class JevIntegrationSettingsOut(BaseModel):
    jev_api_key: SecretStatus
    jev_model: str
    jev_enable: bool
    # True only when enabled AND the key is present, so the UI can say "armed".
    jev_usable: bool


class JevIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jev_api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    jev_model: str | None = Field(default=None, min_length=1, max_length=128)
    jev_enable: bool | None = None


class JevIntegrationTestOut(BaseModel):
    """Result of a real systemone call against TypeSafe."""

    ok: bool
    configured: bool
    missing: list[str]
    latency_ms: int | None = None
    sample: str | None = None
    error: str | None = None


# ─── TingTing app API (employee password reset) ─────────────────────────────
# Deployment-wide, not per-project: one API key authenticates the reset flow for
# every tenant, and the workflow guide is embedded in the backend, so the admin
# configures exactly one secret.


class TingtingIntegrationSettingsOut(BaseModel):
    api_key: SecretStatus
    # True only when a usable key is stored — the gate for the embedded guide.
    configured: bool
    base_url: str
    auth_header: str
    # Internal binding: the account key of the verified support OA, set by the
    # link below. Kept in the response for diagnostics; the settings page shows
    # the OA name/id instead of this key.
    reset_oa_id: str = ""
    # The escalation hotline the support OA quotes when it cannot help in-chat
    # (operator rule 2026-09-29). Admin-editable; seeded with the approved
    # number, so the settings page shows the live value.
    hotline: str = ""
    # The Zalo OA that serves the reset flow. Credentials are status-only; the
    # OA id and name come from Zalo's `getoa` at link time, never from typing.
    oa_app_id: str = ""
    oa_secret_key: SecretStatus = SecretStatus(configured=False)
    oa_access_token: SecretStatus = SecretStatus(configured=False)
    oa_refresh_token: SecretStatus = SecretStatus(configured=False)
    oa_linked: bool = False
    oa_id: str = ""
    oa_name: str = ""
    oa_label: str = ""
    oa_verified_at: str | None = None
    oa_last_checked_at: str | None = None
    # Redacted reason from the last failed `getoa` probe ("" when it passed).
    oa_last_error: str = ""


class TingtingIntegrationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    # The escalation hotline the support OA quotes when it cannot help in-chat.
    # Stored as sent (after strip); length-capped only, matching the other
    # settings fields — the operator copies the owner-approved number.
    hotline: str | None = Field(default=None, max_length=32)
    # The support OA's four Zalo credentials. Posting any of them (with the API
    # key, or alone) stores what was sent and probes Zalo with the effective
    # access token: on success the OA id/name are discovered and the account is
    # registered; on failure the values are still stored, the response carries
    # `oa_last_error`, and the reset flow stays off.
    zalo_oa_app_id: str | None = Field(default=None, max_length=128)
    zalo_oa_secret_key: str | None = Field(default=None, max_length=2048)
    zalo_oa_access_token: str | None = Field(default=None, max_length=4096)
    zalo_oa_refresh_token: str | None = Field(default=None, max_length=4096)


# ─── Facebook / Messenger (Phase 4) ─────────────────────────────────────────
# Privacy contract: no Page token, app secret, or raw PSID ever appears in
# these responses. Page ids are surfaced as a masked suffix only; the safe
# label (Page name) is the recruiter-facing identifier.


class FacebookOAuthStartOut(BaseModel):
    """Returned by POST /facebook/oauth/start — the official authorization URL.

    The opaque ``state`` is a single-use Redis record bound to the initiating
    admin; the frontend never inspects it.
    """

    authorization_url: str


class FacebookOAuthCallbackOut(BaseModel):
    """The opaque result of the OAuth callback redirect.

    The frontend receives only ``flow_id`` + ``status``; no code, no token, no
    Page list. The Page-selection step fetches those server-side via flow_id.
    """

    flow_id: str
    status: str  # "pending_selection" | "error"
    error: str | None = None  # generic, Vietnamese, no provider internals


class FacebookPageOut(BaseModel):
    """One selectable Page during OAuth completion. Safe fields only."""

    id: str  # the Page id is needed to call /complete; it is not PII
    name: str


class FacebookPageListOut(BaseModel):
    pages: list[FacebookPageOut]
    # All currently-active Page ids (multi-Page rollout, plan 260908-1341).
    # Replaces the V1 single ``active_page_id``; the Page id is a routing key,
    # not PII, and is what per-Page endpoints address.
    active_page_ids: list[str] = Field(default_factory=list)


class FacebookAccountStatusOut(BaseModel):
    """One Page account in the safe status response."""

    page_id: str  # the Page id key for per-Page endpoints; not PII
    page_id_suffix: str  # last 4 chars only
    label: str  # safe Page name
    status: str  # "ACTIVE" | "INACTIVE"


class FacebookIntegrationOut(BaseModel):
    """GET /facebook — safe status of all Facebook Page accounts."""

    enabled: bool  # whether the channel is configured at the deployment level
    accounts: list[FacebookAccountStatusOut]


class FacebookChannelTestOut(BaseModel):
    """POST /facebook/test — health probe result."""

    healthy: bool
    error: str | None = None  # generic Vietnamese message
    # None = the webhook-subscription lookup could not run (no Page/token yet,
    # or a provider failure); False = the app is not receiving Page events.
    app_subscribed: bool | None = None


class FacebookOAuthCompleteRequest(BaseModel):
    """POST /facebook/oauth/complete — select one Page to activate."""

    flow_id: str
    page_id: str
    # Optional replace-all Project assignment applied atomically with
    # activation (multi-Page rollout). Absent → keep any existing assignment
    # (same-Page reconnection resumes it); an explicit empty list means "no
    # assignment", which the D1 activation gate rejects with 409.
    project_ids: list[str] | None = None


class FacebookPageProjectAssignmentOut(BaseModel):
    """One Page↔Project assignment in the per-Page assignment editor payload."""

    project_id: str
    project_slug: str
    project_name: str
    project_active: bool  # current Project is_active flag (editor hint)


class FacebookPageProjectsOut(BaseModel):
    """GET/PUT/POST/DELETE /facebook/pages/{page_id}/projects responses."""

    page_id: str
    assignments: list[FacebookPageProjectAssignmentOut] = Field(default_factory=list)


class FacebookPageProjectsUpdate(BaseModel):
    """PUT /facebook/pages/{page_id}/projects — replace-all save (multi-select)."""

    model_config = ConfigDict(extra="forbid")

    project_ids: list[str]


class FacebookPageProjectAdd(BaseModel):
    """POST /facebook/pages/{page_id}/projects — add one Project."""

    model_config = ConfigDict(extra="forbid")

    project_id: str


class FacebookCredentialsOut(BaseModel):
    """GET /facebook/credentials — safe status of the app-level Meta credentials.

    ``app_id`` and ``login_config_id`` are not secret (they appear in the
    browser OAuth URL) so their actual value is surfaced for editing.
    ``app_secret`` and ``verify_token`` expose only a masked preview like other
    secrets — leaving a field blank on PUT keeps the stored value unchanged.
    """

    facebook_app_id: PlainStatus
    facebook_app_secret: SecretStatus
    facebook_login_config_id: PlainStatus
    facebook_webhook_verify_token: SecretStatus


class FacebookCredentialsReveal(BaseModel):
    """POST /facebook/credentials/reveal — plaintext secrets for an admin.

    Deliberately separate from the masked GET view. Re-registering the webhook
    on Meta requires the verify token verbatim, and rotating it just to read it
    forces a needless re-registration everywhere it is already configured.
    """

    facebook_app_secret: str | None = None
    facebook_webhook_verify_token: str | None = None


class FacebookCredentialsUpdate(BaseModel):
    """PUT /facebook/credentials — partial update of Meta app credentials.

    All fields are optional: a null / absent field is left unchanged ("leave
    blank to keep current value" semantics). Empty / whitespace-only values
    are dropped by the service layer before write.
    """

    model_config = ConfigDict(extra="forbid")

    facebook_app_id: str | None = Field(default=None, min_length=1, max_length=128)
    facebook_app_secret: str | None = Field(default=None, min_length=8, max_length=256)
    facebook_login_config_id: str | None = Field(
        default=None, min_length=1, max_length=256
    )
    facebook_webhook_verify_token: str | None = Field(
        default=None, min_length=4, max_length=256
    )
