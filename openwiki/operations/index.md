# Files

- [Configuration, settings, and ownership of env keys](configuration.md) - Settings split between code constants (Zalo endpoints, EMBEDDING_DIM, DIGEST_*), Settings() env-loaded fields (DB pool, intervals, CORS, secrets), and admin-managed runtime credentials.
- [Logging, structured context, and observability](observability.md) - setup_logging + request_id_ctx middleware, what gets logged and what never does (secrets/PII/message content), and how the decision trace ties into recruiter-visible bot_runs.
- [Testing pyramid, integration lane, and E2E harness](testing-strategy.md) - Test layers (unit, integration, API, E2E Playwright, RAG benchmark), the disposable PostgreSQL integration lane, and the E2E harness that boots a real stack.
