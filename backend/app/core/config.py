"""Application settings loaded from environment (.env in dev).

Secrets (Zalo token, MiniMax/Gemini keys, DB password, JWT secret) live here and
must NEVER reach the frontend — the CRM holds only the user JWT.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # LLM: MiniMax (OpenAI-compatible). Agent + safety. KEPT from n8n, prompts ported verbatim.
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_agent_model: str = "MiniMax-M2.7-highspeed"
    minimax_safety_model: str = "MiniMax-M2.5-highspeed"
    minimax_request_timeout: int = 60

    # Embeddings: Google Gemini (3072-dim). KEPT from n8n.
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 3072

    # LLM "training pipeline" — MiniMax digests raw KB files into RAG units + builds
    # the per-project catalog card. Falls back to the agent model when unset.
    minimax_digest_model: str = ""
    # Generous per-call ceiling for the BACKGROUND digest. M2.7 always reasons, so a
    # digest section legitimately takes longer than a chat turn; the chat/agent/safety
    # paths keep using minimax_request_timeout (60s). On timeout the pipeline falls back
    # to source-grounded units instead of failing the document (see KnowledgePipeline).
    minimax_digest_timeout: int = 180
    kb_storage_path: str = "/data/kb_uploads"
    digest_section_chars: int = 6000
    digest_max_sections: int = 20
    ingest_job_timeout_seconds: int = 3600

    web_concurrency: int = 2

    # Per-chat bot mutex TTL. Must comfortably exceed the worst-case single turn
    # (agent 60s MiniMax timeout + a safety retry + overhead). A worker crash
    # mid-turn is handled by TTL expiry (the next inbound can then re-acquire);
    # the `version` optimistic token in recheck_ownership is the real guard
    # against a stale run sending after a takeover.
    bot_lock_ttl_seconds: int = 180

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
