"""Application settings loaded from environment (.env in dev).

Secrets (Zalo token, MiniMax/Gemini keys, DB password, JWT secret) live here and
must NEVER reach the frontend — the CRM holds only the user JWT.
"""

from functools import lru_cache
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Zalo API endpoints (code constants, not admin-editable runtime settings)
# ---------------------------------------------------------------------------
ZALO_BOT_API_BASE: str = "https://bot-api.zaloplatforms.com"
ZALO_OA_API_BASE: str = "https://openapi.zalo.me"

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


# ---------------------------------------------------------------------------
# Embedding vector dimension (schema-pinned, not freely configurable)
# ---------------------------------------------------------------------------
# pgvector stores embeddings as vector(3072) (migration 0001) and the ANN
# candidate index is halfvec(3072) HNSW (migrations 0014/0016). The embedding
# model's output dimension must equal this value: a mismatch breaks both writes
# (wrong-width vector column) and ANN retrieval, so the retrieval layer gates ANN
# on it and warns on drift instead of silently degrading to exact search.
EMBEDDING_DIM: int = 3072


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:5173"

    # Database
    database_url: str = "postgresql+asyncpg://vfic:vfic@localhost:5432/vfic"
    database_url_sync: str = "postgresql+psycopg://vfic:vfic@localhost:5432/vfic"
    # Async engine pool sizing. Connection budget: a deployment's peak DB
    # connections ≈ (# DB-touching processes) × (db_pool_size + db_max_overflow).
    # With 2 web + 6 chatbot replicas + followup/ingest/persistence/reconcile/
    # scheduler workers (~13 processes) at 10+10, raise Postgres max_connections
    # to ≥150, or lower these via env on a small box. pool_recycle proactively
    # refreshes connections before server-side idle timeouts stale them; paired
    # with pool_pre_ping it removes intermittent "connection already closed".
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout: int = 30  # seconds to wait for a free connection before raising
    db_pool_recycle: int = 1800  # recycle connections every 30 min

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
    # Server-side key for encrypting admin-managed integration secrets at rest.
    # Dev may fall back to JWT_SECRET for local ergonomics; production must set it.
    integration_settings_encryption_key: str = ""

    # Zalo Bot Platform (bot-api.zaloplatforms.com/bot{TOKEN}/...) — the single
    # Zalo integration for inbound + outbound. `zalo_bot_token` rides in the URL
    # path; `zalo_bot_webhook_secret` verifies inbound via X-Bot-Api-Secret-Token.
    # Values here are bootstrap/dev fallbacks. In production the admin UI writes
    # the same credentials to integration_settings, which runtime code prefers.
    zalo_bot_token: str = ""
    zalo_bot_webhook_secret: str = ""
    # Per-call HTTP timeout (s). Zalo recommends 30s for getUpdates long-polling;
    # sender methods usually complete in <5s, but we leave headroom.
    zalo_bot_request_timeout: int = 30
    # The webhook URL currently registered with Zalo (used for self-tests / status).
    zalo_bot_webhook_url: str = ""
    # Zalo Official Account bootstrap/dev fallbacks. API base is a code constant:
    # app.core.config.ZALO_OA_API_BASE.
    zalo_oa_app_id: str = ""
    zalo_oa_secret_key: str = ""
    zalo_oa_access_token: str = ""
    zalo_oa_refresh_token: str = ""

    # LLM providers. MiniMax is the default primary provider; OpenRouter is also
    # OpenAI-compatible and can be selected via *_ENABLE.
    minimax_enable: bool = True
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_agent_model: str = "MiniMax-M2.7-highspeed"
    minimax_safety_model: str = "MiniMax-M2.5-highspeed"
    minimax_request_timeout: int = 60

    OPENROUTER_DEFAULT_MODEL: ClassVar[str] = "deepseek/deepseek-v4-flash"

    openrouter_enable: bool = False
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_agent_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_safety_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_digest_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_request_timeout: int = 60
    openrouter_digest_timeout: int = 180

    # Embeddings: OpenRouter by default (3072-dim) so knowledge indexing and
    # retrieval can use the same admin-managed OpenRouter credential path as
    # the digest/chat models. Gemini remains available as an explicit fallback
    # provider for environments that still carry the older key.
    embedding_provider: str = "openrouter"
    openrouter_embedding_model: str = "openai/text-embedding-3-large"
    openrouter_embedding_timeout: int = 60
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = EMBEDDING_DIM

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
    # stuck turn before its per-conversation lock auto-expires. Lowered 150→11: the
    # propagated deadline below now bounds every healthy turn, so this is purely a
    # safety net for a worker that has escaped the deadline logic.
    chat_turn_job_timeout: int = 11

    # ── ~10-second perceived-responsiveness budget ─────────────────────────────
    # The webhook stamps received_at_epoch; the worker sets deadline_at_epoch =
    # received_at_epoch + sla_seconds. Each graph stage checks _remaining()
    # (epoch-based so it crosses the FastAPI→RQ process boundary). agent_max_seconds
    # is the inner asyncio.wait_for ceiling on the agent turn; send_margin_seconds
    # reserves time for the Zalo POST + DB commit; soft_fallback_remaining stops
    # starting expensive work when little time is left.
    sla_seconds: float = 10.0
    agent_max_seconds: float = 8.5
    send_margin_seconds: float = 1.0
    soft_fallback_remaining: float = 2.0

    # Phase 2 scaling knobs (env-tunable). 0 = disabled (pass-through).
    # LLM/embed semaphores are ENABLED by default (see graph/llm_semaphore.py):
    # a Redis token list throttles concurrent provider calls across ALL worker
    # processes so a burst doesn't trip MiniMax/Gemini 429s. A turn that can't
    # acquire a token within 30s proceeds anyway (degraded) — no deadlock risk.
    # Tune from 429/latency metrics; raise if normal-load latency suffers.
    llm_concurrency_limit: int = 4  # max concurrent LLM calls, deployment-wide
    max_llm_calls_per_turn: int = (
        6  # agent tool-loop ceiling (replaces hardcoded DEFAULT_MAX_ITERS)
    )
    embed_concurrency_limit: int = 6  # max concurrent embed calls (ingest + retrieval), deployment-wide
    # Backpressure: reject enqueue when webhook_high depth reaches this.
    # 0 = disabled.  Set to ~2x worker-chatbot replicas so Zalo retries later.
    chat_queue_max_depth: int = 40

    # Reconcile sweep — recovers lost bot turns after worker crash / restart.
    reconcile_interval_seconds: int = 60  # sweep cadence
    reconcile_grace_seconds: int = 120  # min age before a msg is considered stuck
    reconcile_max_age_seconds: int = 86400  # 24h cap
    reconcile_batch_size: int = 50  # per-tick candidate cap

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
        raise RuntimeError(
            "No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true"
        )

    @property
    def llm_fallback_enabled(self) -> bool:
        return self.minimax_enable and self.openrouter_enable

    @property
    def active_llm_request_timeout(self) -> int:
        return (
            self.openrouter_request_timeout
            if self.active_llm_provider == "OpenRouter"
            else self.minimax_request_timeout
        )

    @property
    def active_llm_digest_timeout(self) -> int:
        return (
            self.openrouter_digest_timeout
            if self.active_llm_provider == "OpenRouter"
            else self.minimax_digest_timeout
        )

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
        if self.app_env != "development" and not self.integration_settings_encryption_key:
            raise RuntimeError(
                "INTEGRATION_SETTINGS_ENCRYPTION_KEY must be set outside development "
                "so admin-managed integration secrets are encrypted at rest."
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
