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
# Public Bot Platform inbound endpoint registered with Zalo (POST /webhooks/zalo/chatbot).
# A code constant, NOT env — an empty/missing URL is exactly how the app and Zalo
# desync the webhook secret and silently 401-drop all inbound. Update only if the
# public domain changes.
ZALO_BOT_WEBHOOK_URL: str = "https://bot.tingting.vip/webhooks/zalo/chatbot"

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
DIGEST_SECTION_OVERLAP: int = 400
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

    # Process-scoped httpx client pool (Tech-Lead Directive §4 "Reuse
    # connections"). Per-name clients live in app.core.http; these limits size
    # each client's pool. Conservative defaults for the 2-vCPU droplet: enough
    # keepalive slots to avoid handshakes on burst, small enough to stay under
    # the global file-descriptor budget alongside the DB pool.
    http_max_keepalive_connections: int = 10
    http_max_connections: int = 20
    http_keepalive_expiry: int = 30  # seconds an idle keepalive conn is held
    http_default_timeout: float = 30.0  # fallback; callers pass per-request timeouts

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
    # Zalo Official Account bootstrap/dev fallbacks. API base is a code constant:
    # app.core.config.ZALO_OA_API_BASE.
    zalo_oa_app_id: str = ""
    zalo_oa_secret_key: str = ""
    zalo_oa_access_token: str = ""
    zalo_oa_refresh_token: str = ""

    # Facebook Messenger / Meta (Phase 4). These are deployment-owned Meta App
    # credentials only — they identify the Meta App to Graph API. Whether the
    # Messenger CHANNEL is "on" is NOT a deploy-time toggle: it's driven by
    # whether an admin has connected an active Facebook Page via the settings
    # page (an active ChannelAccount row), exactly like how Zalo Chatbot / Zalo
    # OA are considered configured once their credentials are in the integration
    # settings. Graph API version is pinned centrally so a Meta deprecation
    # surfaces as one config change, not a code hunt.
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_login_config_id: str = ""
    meta_webhook_verify_token: str = ""
    meta_graph_api_version: str = "v25.0"
    meta_graph_api_base: str = "https://graph.facebook.com"
    # Exact allowlist for OAuth callback redirect URIs (production origins).
    # Empty in dev (localhost callbacks permitted).
    facebook_callback_allowlist: list[str] = []

    # LLM providers. These are bootstrap/dev defaults; production can override
    # enable/default/model choices from the admin-managed integration settings.
    llm_default_provider: str = "minimax"
    minimax_enable: bool = True
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"
    minimax_agent_model: str = "MiniMax-M2.7-highspeed"
    minimax_safety_model: str = "MiniMax-M2.5-highspeed"
    minimax_request_timeout: int = 60
    # Fast-tier model for low-complexity intents (Phase 5 model tiering). Empty = disabled
    # (every intent uses the reasoning agent model, the pre-tiering default). When set,
    # ``small_talk``/``contact``/simple ``faq_detail`` turns use this lighter model.
    minimax_fast_model: str = ""

    OPENROUTER_DEFAULT_MODEL: ClassVar[str] = "deepseek/deepseek-v4-flash"

    openrouter_enable: bool = False
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_agent_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_safety_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_digest_model: str = OPENROUTER_DEFAULT_MODEL
    # OpenRouter fast-tier for low-complexity intents (Phase 5). Empty = use agent model.
    openrouter_fast_model: str = ""
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
    rag_rrf_rank_constant: int = 60
    rag_cache_enabled: bool = True
    rag_result_cache_ttl_seconds: int = 300
    embedding_cache_ttl_seconds: int = 86400

    # Semantic cache (Phase 5): similarity-based dedup for non-personalized knowledge
    # queries. Only ``search_knowledge`` (FAQ/contact/detail) is cached — never
    # recommendation/profile/memory (personalized). Off by default; enable after
    # confirming no false-positive cross-topic hits on the gold set.
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = 0.95  # cosine similarity required for a hit
    semantic_cache_capacity: int = 200  # max cached queries (LRU-evicted)
    semantic_cache_ttl_seconds: int = 1800  # 30 min

    # Token/cost accounting (Phase 6). Per-million-token USD rates for cost estimation.
    # Default to MiniMax M2.7 documented rates; set to 0 to track tokens only (cost=0).
    llm_cost_per_mtok_input: float = 1.0
    llm_cost_per_mtok_output: float = 5.0
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
    # stuck turn before its per-conversation lock auto-expires. This is a HANG-ONLY
    # backstop: the agent turn is no longer hard-capped (see agent_max_seconds), so
    # this must comfortably exceed any realistic LLM turn (~10-30s) — only a truly
    # wedged provider call is reaped here, and the reconcile sweeper recovers it.
    # LOAD-BEARING INVARIANT: reconcile_grace_seconds MUST exceed this value. F6's
    # break_stale_lock force-breaks a lock whose heartbeat is older than this
    # threshold; the grace window guarantees a candidate only appears after RQ has
    # already killed the job, so a live (slow-but-legitimate) turn is never stolen.
    chat_turn_job_timeout: int = 60
    # Direct ASGI turns renew their owner-token lease on this cadence. Keep this
    # comfortably below ``chat_turn_job_timeout`` because reconciliation uses
    # that threshold to identify a dead turn.
    direct_turn_heartbeat_seconds: float = 20.0

    # ── perceived-responsiveness budget ────────────────────────────────────────
    # The webhook stamps received_at_epoch; the worker sets deadline_at_epoch =
    # received_at_epoch + sla_seconds. The deadline is ADVISORY: it bounds the
    # FAQ-bypass lookup budget only — it never cancels the agent (cancelling live
    # LLM calls produced excessive TIMEOUT fallbacks in prod). send_margin_seconds
    # reserves time for the Zalo POST + DB commit; soft_fallback_remaining stops
    # starting expensive bypass work when little time is left.
    sla_seconds: float = 10.0
    # Retired as a hard cap — the agent is no longer wrapped in asyncio.wait_for
    # and runs to completion. Kept as an advisory reference / for future use; it
    # no longer enforces a timeout on the agent turn.
    agent_max_seconds: float = 8.5
    send_margin_seconds: float = 1.0
    soft_fallback_remaining: float = 2.0
    # Per-stage turn budgets (Tech-Lead Directive §4 "Use hard deadlines"). These
    # bound the CHEAP, derived stages only — retrieval (vector + lexical arms),
    # rerank. The agent LLM generation is deliberately NOT bounded here; see
    # app/graph/deadlines.py docstring for the production rationale. Defaults
    # leave headroom under sla_seconds for the uncapped agent + send.
    turn_retrieval_budget_seconds: float = 1.2
    turn_rerank_budget_seconds: float = 0.6
    # Single-flight request coalescing (Tech-Lead Directive §6): when N concurrent
    # turns ask the same uncached question, only one process calls the model; the
    # others await the same result via Redis pub/sub. Applies ONLY to non-
    # personalized, non-scoped search_knowledge lookups. Off by default — enable
    # after confirming no cross-topic false-positive coalescing on the gold set.
    singleflight_enabled: bool = False
    # ── P3-2 retrieval tuning (Tech-Lead Directive §12 + §16 P3) ──
    # RRF fusion weights + rerank conditionality. Defaults are starting points;
    # P3-2's benchmark harness (scripts/eval_retrieval.py) measures quality at
    # each config and picks the winner against the golden dataset (P3-1).
    # RRF rank constant: higher favors top ranks from each arm.
    rag_lexical_weight: float = 1.0  # multiplier on lexical arm rank in fusion
    rag_vector_weight: float = 1.0  # multiplier on vector arm rank in fusion
    # Conditional reranking (directive §12): skip the reranker when the candidate
    # set is unambiguous.Off by default; the score-blend reranker stays disabled
    # (rag_rerank_enabled above) until P3-2 demonstrates a precision lift.
    rag_rerank_conditional: bool = True
    rag_rerank_skip_on_single_match: bool = True  # skip when only 1 candidate
    rag_rerank_skip_on_exact_id: bool = True  # skip when an exact job code / route matched
    # ── P3-3 release gates (Tech-Lead Directive §16 P3) ──
    # Toggle whether the deploy pipeline blocks on SLO regressions. The CI job
    # runs the golden dataset + a short load-test; these flags gate its verdict.
    release_gate_correctness_enabled: bool = True
    release_gate_latency_slo_enabled: bool = True
    # Per-SLO deploy-blocking thresholds (matched against /admin/performance/slos).
    release_gate_full_answer_p95_ms: int = 4000
    release_gate_error_rate_pct: float = 1.0
    # Active-status signal (Priority #1 — the psychological bridge). typing_heartbeat_seconds
    # pulses send_chat_action("typing") (real on the Bot channel; a logged no-op on OA).
    typing_heartbeat_seconds: float = 3.5
    # FAQ/template fast lane (Priority #3). When enabled, common non-factual traffic
    # (greetings / thanks / goodbye / help) is answered from deterministic tôi/bạn
    # templates with ZERO LLM calls. Factual questions are never templated here — they
    # stay on the RAG + agent path.
    faq_fast_lane_enabled: bool = True
    # Phase 4 messaging-hardening: when the top FAQ-bypass match is only this much
    # better than the runner-up (similarity delta < margin), abstain to the LLM
    # instead of trusting a low-confidence answer. 0.0 = never abstain on margin
    # (preserve legacy behavior). Tune from the performance dashboard's abstention
    # rate after a week of production data.
    faq_abstain_margin: float = 0.03
    # Minimum time slice required to safely start an LLM call (TTFT + a meaningful token
    # span). If _remaining() < send_margin_seconds + min_llm_time_budget, skip the LLM and
    # send a human fallback — a 2-3s slice cannot complete a useful generation.

    # Phase 2 scaling knobs (env-tunable). 0 = disabled (pass-through).
    # LLM/embed semaphores are ENABLED by default (see graph/llm_semaphore.py):
    # a Redis token list throttles concurrent provider calls across ALL worker
    # processes so a burst doesn't trip MiniMax/Gemini 429s. A turn that can't
    # acquire a token within llm_acquire_timeout_seconds fail-fasts (raises
    # LLMThrottled → DEGRADATION_REPLY + mutex clear) rather than queueing
    # silently — no ~30s stall, no deadlock risk.
    # Tune from 429/latency metrics; raise concurrency if normal-load latency suffers.
    llm_concurrency_limit: int = 8  # max concurrent LLM calls, deployment-wide
    llm_acquire_timeout_seconds: float = 1.5  # BLPOP wait before LLMThrottled
    llm_429_retry_sleep_seconds: float = 0.5  # backoff between the two 429 attempts
    max_llm_calls_per_turn: int = (
        6  # agent tool-loop ceiling (replaces hardcoded DEFAULT_MAX_ITERS)
    )
    embed_concurrency_limit: int = (
        6  # max concurrent embed calls (ingest + retrieval), deployment-wide
    )
    # Parallel tool dispatch: when the LLM returns multiple tool_calls in one
    # response, run them concurrently (each on its own DB session) instead of
    # sequentially. Caps simultaneous calls so a model returning many tool_calls
    # can't exhaust the DB pool (pool_size + max_overflow per process).
    parallel_tool_max_concurrency: int = 4
    # Backpressure: reject enqueue when webhook_high depth reaches this.
    # 0 = disabled.  Set to ~2x worker-chatbot replicas so Zalo retries later.
    chat_queue_max_depth: int = 40

    # Structured Job↔Lead recommendation engine weights (Phase 2).
    # MiniMax §7.2: "weights must be re-tuned against labeled hires after the
    # first 1,000 production conversations; this is a starting point."
    rec_weight_title: float = 0.35  # desired_job ↔ job.title overlap
    rec_weight_salary: float = 0.25  # expected_salary band overlap
    rec_weight_location: float = 0.20  # living_area/region ↔ province/district
    rec_weight_support: float = 0.10  # accommodation/transport flag match
    rec_weight_experience: float = 0.10  # years_experience fit / "no exp required" bonus
    rec_top_k: int = 5  # default shortlist size

    # Grounding enforcement (Phase 3): strip job_ids the reply cites that were not
    # in the tool results shown to the LLM. Best-effort; never blocks a turn.
    grounding_check_enabled: bool = True

    # Retrieval reranker (Phase 4). The knowledge path already fuses via RRF; this
    # adds an optional score-blend rerank tail on the fused top-K. Off by default —
    # enable after measuring a precision lift on the gold set. The interface
    # (Reranker) is ready for a hosted cross-encoder backend later.
    rag_rerank_enabled: bool = False

    # Reconcile sweep — recovers lost bot turns after worker crash / restart.
    reconcile_interval_seconds: int = 60  # sweep cadence
    # MUST exceed chat_turn_job_timeout (F6 safety — see break_stale_lock): a
    # candidate only surfaces after this grace, by which point RQ has killed the
    # job, so a stale-heartbeat lock is always a dead worker, never a live turn.
    reconcile_grace_seconds: int = 120  # min age before a msg is considered stuck
    reconcile_max_age_seconds: int = 86400  # 24h cap
    reconcile_batch_size: int = 50  # per-tick candidate cap
    decision_trace_retention_days: int = 30
    decision_trace_retention_batch_size: int = 200
    decision_trace_retention_interval_seconds: int = 86400  # daily

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def active_llm_provider(self) -> str:
        """Primary LLM provider from env/bootstrap settings."""
        default_provider = (self.llm_default_provider or "minimax").strip().lower()
        if default_provider == "openrouter" and self.openrouter_enable:
            return "OpenRouter"
        if default_provider == "minimax" and self.minimax_enable:
            return "MiniMax"
        if self.minimax_enable:
            return "MiniMax"
        if self.openrouter_enable:
            return "OpenRouter"
        raise RuntimeError(
            "No LLM provider enabled: set MINIMAX_ENABLE=true or OPENROUTER_ENABLE=true"
        )

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
