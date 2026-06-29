"""Application settings loaded from environment (.env in dev).

Secrets (Zalo token, MiniMax/Gemini keys, DB password, JWT secret) live here and
must NEVER reach the frontend — the CRM holds only the user JWT.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Proactive follow-up constants (not configurable via env — policy is in code)
# ---------------------------------------------------------------------------
PROACTIVE_FOLLOWUP_GAPS_HOURS: list[int] = [6, 24, 46]
PROACTIVE_FOLLOWUP_CAP: int = 3
PROACTIVE_SILENCE_LIMIT: int = 2
PROACTIVE_TICK_INTERVAL_SECONDS: int = 1800  # 30 min
PROACTIVE_PER_TICK_CAP: int = 5
# 48h Zalo rule minus 1h safety margin for in-flight latency (MiniMax + safety).
PROACTIVE_48H_WINDOW_SECONDS: int = 169200  # 47h
PROACTIVE_RETRY_COOLDOWN_SECONDS: int = 21600  # 6h
PROACTIVE_JOB_MAX_AGE_SECONDS: int = 3300  # 55 min
# Vietnamese + English opt-out phrases (substring match on inbound).
PROACTIVE_OPTOUT_PHRASES: list[str] = [
    p.strip().lower()
    for p in (
        "dừng,đừng nhắn,ko quan tâm,không quan tâm,stop,unsubscribe,để yên,bận rồi,"
        "đừng làm phiền,không cần nữa,tôi không thích,không thích"
    ).split(",")
    if p.strip()
]

# ---------------------------------------------------------------------------
# Knowledge pipeline constants (not configurable via env)
# ---------------------------------------------------------------------------
DIGEST_SECTION_CHARS: int = 6000
DIGEST_MAX_SECTIONS: int = 20
INGEST_JOB_TIMEOUT_SECONDS: int = 3600


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:5173"

    # Database
    database_url: str = "postgresql+asyncpg://vfic:vfic@localhost:5432/vfic"
    database_url_sync: str = "postgresql+psycopg://vfic:vfic@localhost:5432/vfic"

    # Redis (RQ broker + per-chat mutex + pub/sub)
    redis_url: str = "redis://localhost:6379/0"

    # Auth (replaces Supabase Auth)
    jwt_secret: str = "dev-only-change-me-32-chars-minimum"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14
    resend_api_key: str = ""
    password_reset_otp_ttl_minutes: int = 10
    password_reset_otp_attempt_limit: int = 5

    # Zalo Bot Platform (bot-api.zaloplatforms.com/bot{TOKEN}/...) — the single
    # Zalo integration for inbound + outbound. `zalo_bot_token` rides in the URL
    # path; `zalo_bot_webhook_secret` verifies inbound via X-Bot-Api-Secret-Token.
    zalo_bot_token: str = ""
    zalo_bot_webhook_secret: str = ""
    zalo_bot_api_base: str = "https://bot-api.zaloplatforms.com"
    # Per-call HTTP timeout (s). Zalo recommends 30s for getUpdates long-polling;
    # sender methods usually complete in <5s, but we leave headroom.
    zalo_bot_request_timeout: int = 30
    # The webhook URL currently registered with Zalo (used for self-tests / status).
    zalo_bot_webhook_url: str = ""

    # LLM providers. MiniMax remains the default for backwards compatibility;
    # OpenRouter is also OpenAI-compatible and can be selected via *_ENABLE.
    minimax_enable: bool = True
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_agent_model: str = "MiniMax-M2.7-highspeed"
    minimax_safety_model: str = "MiniMax-M2.5-highspeed"
    minimax_request_timeout: int = 60

    openrouter_enable: bool = False
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_agent_model: str = "deepseek/deepseek-v3.2"
    openrouter_safety_model: str = "deepseek/deepseek-v3.2"
    openrouter_digest_model: str = "deepseek/deepseek-v3.2"
    openrouter_request_timeout: int = 60
    openrouter_digest_timeout: int = 180

    # Embeddings: Google Gemini (3072-dim). KEPT from n8n.
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 3072

    # Retrieval scaling. ``rag_ann_enabled`` uses pgvector halfvec HNSW for
    # candidate generation, then exact vector re-ranking preserves result quality.
    rag_ann_enabled: bool = True
    rag_ann_candidates: int = 200
    rag_cache_enabled: bool = True
    rag_result_cache_ttl_seconds: int = 300
    embedding_cache_ttl_seconds: int = 86400
    dashboard_cache_enabled: bool = True
    dashboard_cache_ttl_seconds: int = 30

    # LLM "training pipeline" — MiniMax digests raw KB files into RAG units + builds
    # the per-project catalog card. Falls back to the agent model when unset.
    minimax_digest_model: str = ""
    # Generous per-call ceiling for the BACKGROUND digest. M2.7 always reasons, so a
    # digest section legitimately takes longer than a chat turn; the chat/agent/safety
    # paths keep using minimax_request_timeout (60s). On timeout the pipeline falls back
    # to source-grounded units instead of failing the document (see KnowledgePipeline).
    minimax_digest_timeout: int = 180
    kb_storage_path: str = "/data/kb_uploads"

    web_concurrency: int = 2

    # Per-chat bot mutex TTL. Must comfortably exceed the worst-case single turn
    # (agent 60s MiniMax timeout + a safety retry + overhead). A worker crash
    # mid-turn is handled by TTL expiry (the next inbound can then re-acquire);
    # the `version` optimistic token in recheck_ownership is the real guard
    # against a stale run sending after a takeover.
    bot_lock_ttl_seconds: int = 180
    # RQ job timeout for chat turns. Must be < bot_lock_ttl_seconds so RQ kills a
    # stuck turn before its per-conversation lock auto-expires (avoids stale-run
    # window where a new inbound re-acquires the lock while the old turn is dying).
    chat_turn_job_timeout: int = 150

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def active_llm_provider(self) -> str:
        """Primary LLM provider. MiniMax is always primary when enabled; OpenRouter acts as fallback."""
        if self.openrouter_enable and not self.minimax_enable:
            return "OpenRouter"
        if self.minimax_enable:
            return "MiniMax"
        raise RuntimeError("No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true")

    @property
    def llm_fallback_enabled(self) -> bool:
        return self.minimax_enable and self.openrouter_enable

    @property
    def active_llm_request_timeout(self) -> int:
        return self.openrouter_request_timeout if self.active_llm_provider == "OpenRouter" else self.minimax_request_timeout

    @property
    def active_llm_digest_timeout(self) -> int:
        return self.openrouter_digest_timeout if self.active_llm_provider == "OpenRouter" else self.minimax_digest_timeout

    def model_post_init(self, __context) -> None:
        """Fail fast if the deployed environment keeps the dev JWT secret.

        A prod instance that forgets to set ``JWT_SECRET`` would otherwise silently
        sign tokens with a value committed to the repo, letting anyone forge admin
        JWTs. ``app_env == development`` (tests/local) keeps the default for ergonomics.
        """
        if self.app_env != "development" and self.jwt_secret == _DEV_DEFAULT_JWT_SECRET:
            raise RuntimeError(
                "JWT_SECRET must be overridden outside development "
                "(the committed default is public and forgeable)."
            )
        # allow_credentials=True is hardcoded in main.py (JWT in the Authorization
        # header needs credentialed CORS). A wildcard '*' origin with credentials
        # is both rejected by browsers AND a credential-leaking misconfiguration,
        # so refuse to boot rather than silently degrade.
        if "*" in self.cors_origins_list:
            raise RuntimeError(
                "CORS_ORIGINS must not contain '*' — credentials are enabled "
                "(set an explicit origin list)."
            )


_DEV_DEFAULT_JWT_SECRET = "dev-only-change-me-32-chars-minimum"


@lru_cache
def get_settings() -> Settings:
    return Settings()
