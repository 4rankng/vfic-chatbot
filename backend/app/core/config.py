"""Application settings loaded from environment (.env in dev).

Secrets (Zalo token, MiniMax/Gemini keys, DB password, JWT secret) live here and
must NEVER reach the frontend — the CRM holds only the user JWT.
"""

from functools import lru_cache
from typing import ClassVar

from pydantic import AliasChoices, Field, field_validator
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

# Signing algorithms this service may issue/accept (SEC-08). Code-owned: a
# misconfigured JWT_ALGORITHM must fail at boot, not break every login at
# request time.
ALLOWED_JWT_ALGORITHMS: frozenset[str] = frozenset({"HS256", "HS384", "HS512"})

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
    # TrustedHost allowlist for Starlette's TrustedHostMiddleware (SEC-06). Bare
    # hostnames only (no scheme, no port); '*' is refused at boot because it turns
    # the host allowlist into a no-op. bot.tingting.vip is the production console
    # origin (same domain as the ZALO_BOT_WEBHOOK_URL code constant); localhost /
    # 127.0.0.1 keep the compose healthchecks, the in-container post-flip probe,
    # and local dev working.
    allowed_hosts: str = "bot.tingting.vip,localhost,127.0.0.1"

    # Database
    database_url: str = "postgresql+asyncpg://vfic:vfic@localhost:5432/vfic"
    database_url_sync: str = "postgresql+psycopg://vfic:vfic@localhost:5432/vfic"
    # Async engine pool sizing. Connection budget: a deployment's peak DB
    # connections ≈ (# DB-touching processes) × (db_pool_size + db_max_overflow).
    # Resident DB-touching processes (docker-compose.yml): web-blue + web-green
    # (one uvicorn each) and workers chatbot ×3, persistence, ingest, followup,
    # maintenance — 9 total. Compose sets web services to 8+4 and each worker to
    # 4+2, so the worst case is 2×12 + 7×6 = 66 of the Postgres
    # max_connections=150 ceiling (~44%), leaving headroom for adminer/psql and
    # the one-shot backfill profile. pool_recycle proactively refreshes
    # connections before server-side idle timeouts stale them; paired with
    # pool_pre_ping it removes intermittent "connection already closed".
    db_pool_size: int = 10
    db_max_overflow: int = 10
    # Saturation must fail fast into the recovery path — a wait three times the
    # perceived-responsiveness SLA (30s) only holds the per-chat lock past the
    # point where the answer is useful.
    db_pool_timeout: int = 5  # seconds to wait for a free connection before raising
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
    # SEC-08: every token this service mints carries `iss`/`aud` and every decode
    # requires them, so a token minted for a sibling service that happens to share
    # the same secret is not interchangeable across trust boundaries. Both are
    # configurable so a future split (e.g. a separate admin audience) is a config
    # change rather than a code change.
    jwt_issuer: str = "tingting-api"
    jwt_audience: str = "tingting-api"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14
    resend_api_key: str = ""
    password_reset_otp_ttl_minutes: int = 10
    password_reset_otp_attempt_limit: int = 5
    # Server-side key for encrypting admin-managed integration secrets at rest.
    # Dev may fall back to JWT_SECRET for local ergonomics; production must set it.
    integration_settings_encryption_key: str = ""

    # Rate limiting (SEC-04). The four auth endpoints keep their dedicated,
    # fail-open limits (app/identity/infrastructure/rate_limits.py). These cover
    # the two previously unbounded surfaces: the inbound webhook POSTs (bucketed
    # per client IP) and the LLM/embedding-backed routes the CRM can fire
    # (`/jobs/search`, `/knowledge/projects/{id}/rag/test`, `/web-chat-turn`,
    # `/leads/{id}/assist`, `/leads/{id}/chatops-actions/*` — bucketed per user,
    # one bucket per route so a burst on a cheap route cannot consume an
    # expensive route's budget). Each bucket admits at most `limit` requests per
    # `window` seconds, and a rejected request never extends that window (Redis
    # counters; see app/core/ratelimit.py).
    ratelimit_webhook_limit: int = 120
    ratelimit_webhook_window_seconds: int = 60
    ratelimit_llm_limit: int = 30
    ratelimit_llm_window_seconds: int = 60
    # Webhook ingress stays fail-open on Redis errors (documented contract: a
    # Redis hiccup must never drop candidate messages). The per-user bucket is
    # the one place fail-closed is defensible — its whole purpose is protecting
    # the deployment-wide LLM/embed token lists — so an operator can opt in.
    ratelimit_llm_fail_closed: bool = False

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
    minimax_agent_model: str = "MiniMax-M3.1-Flash-Preview"
    minimax_extractor_model: str = "MiniMax-M2.5-highspeed"
    minimax_request_timeout: int = 60
    # Fast-tier model for low-complexity intents (Phase 5 model tiering). Empty = disabled
    # (every intent uses the reasoning agent model, the pre-tiering default). When set,
    # ``small_talk``/``contact``/simple ``faq_detail`` turns use this lighter model.
    minimax_fast_model: str = ""

    OPENROUTER_DEFAULT_MODEL: ClassVar[str] = "deepseek/deepseek-v4.1-flash"

    openrouter_enable: bool = False
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_agent_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_extractor_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_digest_model: str = OPENROUTER_DEFAULT_MODEL
    # OpenRouter fast-tier for low-complexity intents (Phase 5). Empty = use agent model.
    openrouter_fast_model: str = ""
    openrouter_request_timeout: int = 60
    openrouter_digest_timeout: int = 180

    # Quota-failover provider. Any OpenAI-compatible chat endpoint (Xiao MiMo,
    # a self-hosted gateway, another vendor) configured entirely from the admin
    # settings page — base URL and model ids are operator-supplied so adding a
    # provider never needs a code change. Used ONLY when the primary provider
    # reports rate-limit/quota exhaustion; see ``_llm_call_with_retry``.
    custom_llm_enable: bool = False
    custom_llm_label: str = "Dự phòng"
    # The generic OpenAI-compatible slot honors the operator's natural export
    # names (e.g. Xiaomi MiMo ships MIMO_API_KEY; OPENAI_BASE_URL is the
    # OpenAI-sdk convention) as env bootstrap; the settings page overrides.
    custom_llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("custom_llm_api_key", "MIMO_API_KEY"),
    )
    custom_llm_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("custom_llm_base_url", "OPENAI_BASE_URL"),
    )
    custom_llm_agent_model: str = ""
    # Empty fast model falls back to the agent model, so one model id is
    # enough to get a working provider.
    custom_llm_fast_model: str = ""
    custom_llm_request_timeout: int = 60

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

    # Geocoding for "dự án nào gần nhà" (project work addresses + the
    # candidate's stated area). The providers are the KEYED hops below, in
    # ``KEYED_GEO_HOPS`` order: Google first, Vietmap second. There is no keyless
    # provider — Nominatim was removed on 2026-10-03 (it answered a factory
    # address with the city centroid behind the wrong "1.5 km" distance, and its
    # 1 req/s policy turned a free fallback into a latency floor), so a
    # deployment with neither key resolves nothing and the catalog omits
    # ``distance_km``. Fail-open everywhere: a geocoder outage must never fail an
    # ingest or a chat turn.
    geocoder_enabled: bool = True
    geocoder_timeout_seconds: float = 3.0
    geocoder_cache_ttl_seconds: int = 2592000  # 30 days (positive hit)
    geocoder_negative_ttl_seconds: int = 21600  # 6 hours (unresolvable query)
    # Keyed geocoder hops, tried in the measured order. Google is primary: on
    # the Hải Phòng plants this bot serves its median positional error against
    # OSM ground truth was 0.92 km against Vietmap's 2.74 km. Vietmap stays as
    # the fallback for when Google is over quota; it is also the only hop that
    # takes the region bias. Both admin-editable via the settings page — the env
    # value only seeds the default. (Map4D was evaluated for this slot but its
    # API was unreachable from the prod host, so it was removed.)
    vietmap_api_key: str = ""
    google_maps_api_key: str = ""

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

    # Answer cache: reuse the previously sent reply for a repeated, non-personalized
    # KB question instead of re-running the agent loop. The exact tier (default ON)
    # requires the same normalized question, the same project scope, the same
    # knowledge/preamble/jobs versions and the same address bucket — nothing that
    # determines the answer changed. The paraphrase tier stays OFF until the
    # calibration harness (scripts/calibrate_answer_cache.py) separates its
    # max(negatives)/min(paraphrases) boundary; the threshold below is the cosine
    # floor a paraphrase must clear.
    answer_cache_enabled: bool = True
    answer_cache_semantic_enabled: bool = False
    answer_cache_threshold: float = 0.95
    answer_cache_capacity: int = 100  # LRU entries per scope (semantic tier only)
    answer_cache_ttl_seconds: int = 21600  # 6 h Redis-reclamation backstop; versions invalidate

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
    # backstop: the agent turn is deliberately uncapped, so this must comfortably
    # exceed any realistic LLM turn (~10-30s) — only a truly wedged provider call
    # is reaped here, and the reconcile sweeper recovers it.
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
    # pre-agent lookup budget only — it never cancels the agent (cancelling live
    # LLM calls produced excessive TIMEOUT fallbacks in prod). send_margin_seconds
    # reserves time for the Zalo POST + DB commit; soft_fallback_remaining stops
    # starting an optional pre-agent lookup when little time is left.
    # NOTE: there is no agent turn cap of any kind. `AGENT_MAX_SECONDS` used to
    # define one and was retired when the agent stopped being wrapped in
    # asyncio.wait_for; the field is gone, and because pydantic-settings is
    # configured with extra="ignore", a leftover AGENT_MAX_SECONDS env var is
    # silently accepted-and-dropped rather than rejected. Setting it does nothing.
    sla_seconds: float = 10.0
    send_margin_seconds: float = 1.0
    soft_fallback_remaining: float = 2.0
    # Turn time-boxing is deadline-at-epoch ONLY: `deadline_at_epoch` (stamped by
    # the webhook from `received_at_epoch + sla_seconds`) bounds the pre-agent
    # lookups and the SLO rollups. There is no per-stage retrieval/rerank budget —
    # the directive-§4 stage budgets were never wired to a production caller and
    # were removed with `app/services/chatbot/{paths,budget,deadlines}.py`
    # (ARCH-03). The agent LLM generation is deliberately uncapped.
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
    # Native Zalo Bot status. Older interval overrides remain accepted, but
    # runtime caps the cadence at three seconds; OA has no typing capability.
    typing_heartbeat_seconds: float = 3.0

    # Phase 2 scaling knobs (env-tunable). 0 = disabled (pass-through).
    # LLM/embed semaphores are ENABLED by default (see graph/llm_semaphore.py):
    # a Redis token list throttles concurrent provider calls across ALL worker
    # processes so a burst doesn't trip MiniMax/Gemini 429s. A turn that can't
    # acquire a token within llm_acquire_timeout_seconds fail-fasts (raises
    # LLMThrottled → suppressed turn + mutex clear) rather than queueing
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
    # Same contract for the low-volume worker queues (enqueue_job applies these
    # as the default bound for their queue; an explicit max_depth at a call site
    # wins). followup bounds per-lead nudge fan-out (~5/30 min); maintenance
    # bounds manual tick triggers — scheduler-enqueued ticks bypass enqueue_job.
    followup_queue_max_depth: int = 50
    maintenance_queue_max_depth: int = 20

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
    # External knowledge-source sync (public Google Sheet → category revision /
    # single-page direct-context file) has no global kill switch: per-link
    # auto_sync_enabled on each *_sync_state row is the sole control. The daily
    # re-ingest cadence is pinned to a wall-clock time via `kb_sync_cron` below
    # so a web-container restart mid-day no longer pushes the next sync out by
    # 24h. Job-timeout/retry remain code constants in the worker modules.
    # Cron expression in UTC, evaluated by rq-scheduler. Default
    # `0 20 * * *` = 03:00 ICT (UTC+7, no DST) — middle of the 2–5 AM low-traffic
    # window. Override per-env to shift the time-of-day. NOTE: "UTC" assumes the
    # container TZ is unset/UTC (the default for python:3.12-slim and our
    # Dockerfile does not override it). If ops ever sets TZ=Asia/Ho_Chi_Minh on
    # the container, this expression would silently shift by 7h — re-express the
    # cron in local time or pin ENV TZ=UTC in that case.
    kb_sync_cron: str = "0 20 * * *"

    @field_validator("kb_sync_cron")
    @classmethod
    def _validate_kb_sync_cron(cls, value: str) -> str:
        # Fail fast at startup on a malformed env value rather than silently
        # mis-firing (or never firing) at the first scheduled tick. rq-scheduler
        # parses with python-crontab (not croniter) — validate with the same
        # parser so accepted/rejected strings match the scheduler exactly.
        from crontab import CronTab

        try:
            CronTab(value)
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"kb_sync_cron must be a valid cron expression (got {value!r})"
            ) from exc
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def _validate_jwt_algorithm(cls, value: str) -> str:
        # SEC-08: an unvalidated env value (e.g. RS256) would silently break
        # every login with a request-time 500 — refuse to boot instead. PyJWT's
        # algorithms= allowlist already rejects `none`, so this only has to pin
        # the HMAC family this single-secret deployment actually uses.
        normalized = value.strip().upper()
        if normalized not in ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"jwt_algorithm must be one of {sorted(ALLOWED_JWT_ALGORITHMS)} "
                f"(got {value!r})"
            )
        return normalized

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

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
        # TrustedHostMiddleware treats '*' as "allow any Host", which turns the
        # host allowlist into a no-op — the exact silent degradation the CORS
        # guard above refuses to boot on.
        if "*" in self.allowed_hosts_list:
            raise RuntimeError(
                "ALLOWED_HOSTS must not contain '*' — the host allowlist is a "
                "security control (set an explicit host list)."
            )


_DEV_DEFAULT_JWT_SECRET = "dev-only-change-me-32-chars-minimum"


@lru_cache
def get_settings() -> Settings:
    return Settings()
