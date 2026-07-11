# Troubleshooting Index

> Index of troubleshooting resources for the ChatBot (VFIC miniCRM) platform.

## Chatbot Response Path (primary debugging resource)

**[`chatbot-response-path.html`](chatbot-response-path.html)** — An interactive HTML troubleshooting map for the full chatbot response pipeline.

Contains:
- Full 16-block pipeline flow (Zalo webhook → bot reply → record outcome)
- Symptom-to-suspect-block decision tree (no reply, slow reply, wrong reply, duplicate, stuck)
- Per-block field manual with failure modes and grep proofs
- Config knobs that affect the pipeline
- Log-grep cheatsheet
- Diagnostic SQL queries for conversation state, messages, bot runs, stuck-PENDING sweeps

**Start here for any bot-related issue.**

---

## Common Issues

### Redis connection failures

**Symptom:** Workers can't enqueue jobs; Socket.IO events not propagating; presence not updating.

**Checks:**
1. Is Redis running? `docker compose -f backend/docker-compose.dev.yml ps redis`
2. Can the app reach it? Check `REDIS_URL` in `backend/.env` (default: `redis://localhost:6379/0`)
3. Redis CLI: `redis-cli ping` → `PONG`
4. Check Redis memory: `redis-cli info memory` — if `used_memory` is near `maxmemory`, evictions may cause silent failures.

**Fix:** Restart Redis: `docker compose -f backend/docker-compose.dev.yml restart redis`. Note: Redis data is ephemeral — a restart clears all caches, presence, and in-flight jobs. The reconcile worker will re-enqueue lost chat turns within 60s.

### OpenRouter 429 (rate limit)

**Symptom:** Bot replies fail with 429 from OpenRouter; LLM calls error out.

**Checks:**
1. Check logs for `429` or `rate_limit` from `graph/clients.py`.
2. Verify `OPENROUTER_API_KEY` is valid and has quota.
3. Check `LLM_CONCURRENCY_LIMIT` — if too high, reduce to stay within provider limits.

**Fix:** The client retries one 429 with a short backoff. If it remains throttled,
the worker sends its static Vietnamese degradation reply; it does not switch to
another LLM provider. Reduce concurrency if 429s are frequent.

### Postgres migration errors

**Symptom:** `alembic upgrade head` fails; app won't start due to schema mismatch.

**Checks:**
1. Current revision: `.venv/bin/alembic current` (from `backend/`)
2. History: `.venv/bin/alembic history`
3. Check for conflicting merge points (the `091e` merge file exists).

**Fix:**
- If a migration is partially applied: `.venv/bin/alembic downgrade -1` then re-run `upgrade head`.
- If the ORM models and schema are out of sync: remember models mirror the schema but do **not** auto-generate migrations. Write a new migration to align them.
- **Never force a migration** without understanding why it failed. Restore from backup if data is corrupted: `make restore`.

### Docker startup issues

**Symptom:** `make dev` fails; containers won't start; port conflicts.

**Checks:**
1. Port 5173 (or custom `PORT`) in use? `lsof -i :5173`
2. Docker running? `docker info`
3. Container logs: `docker compose -f backend/docker-compose.dev.yml logs <service>`
4. Stale containers: `docker compose -f backend/docker-compose.dev.yml down` then retry.

**Fix:** The backend `Makefile` `dev` target runs `kill-port` to free the port before binding. If a stale process blocks it, `kill -9 $(lsof -ti :5173)` then retry.

### LangGraph state recovery

**Symptom:** Bot turns stuck in PENDING; conversations not progressing; duplicate replies.

**Checks:**
1. Query stuck PENDING bot runs (see diagnostic SQL in [`chatbot-response-path.html`](chatbot-response-path.html)).
2. Check reconcile worker: is `run_reconcile_tick` running every 60s? Look for reconcile logs.
3. Check `bot_lock_ttl_seconds` — if the lock TTL is too long, conversations may be stuck waiting for lock expiry.

**Fix:** The reconcile worker (`backend/app/workers/reconcile_worker.py`) automatically finds and re-enqueues stuck bot turns every 60s. If it's not running, check the scheduler registration in `main.py` lifespan. For manual intervention, see the diagnostic SQL queries in the response-path HTML to identify and clear stuck runs.

### Zalo webhook verification

**Symptom:** Webhook receives requests but they're rejected; HMAC signature validation fails.

**Checks:**
1. Verify `ZALO_BOT_TOKEN` / `ZALO_OA_*` credentials in `backend/.env` are correct and current.
2. Check that the Zalo OA app is configured to point to the correct webhook URL (`https://bot.tingting.vip/webhooks/...`).
3. Check logs for HMAC validation errors from `backend/app/api/webhooks.py`.

**Fix:** Zalo OA access tokens expire and must be refreshed. Check `zalo_oa_token_refresh.py` logic and the `zalo_oa_health` endpoint. If the webhook secret changed, update it in `.env` and restart.

**Never disable HMAC validation**, even for testing. Use `backend/mock_servers/` for local development.

### OAuth problems

**Symptom:** Zalo OA OAuth flow fails; can't connect Zalo account; token refresh fails.

**Checks:**
1. Verify `ZALO_OA_APP_ID` and `ZALO_OA_APP_SECRET` in `.env`.
2. Check the OAuth callback URL is correctly registered in the Zalo OA console.
3. Check `backend/app/services/zalo_oa_service.py` and `zalo_oa_token_refresh.py` for token lifecycle issues.
4. Run the test connection endpoint: see `test_zalo_oa_test_connection.py`.

**Fix:** Re-authorize the Zalo OA connection via the integrations page in the recruiter console. If tokens are expired, the token refresh logic should handle it automatically — if not, check `zalo_oa_health.py` for diagnostics.

---

## Additional Resources

| Resource | Purpose |
|---|---|
| [`../deployment-guide.md`](../deployment-guide.md) | Production stack, deploy flow, env vars |
| [`../system-architecture.md`](../system-architecture.md) | Runtime architecture, queue model, data layer |
| [`../DROPLET-BACKUP-RESTORE.md`](../DROPLET-BACKUP-RESTORE.md) | Full droplet backup/restore runbook |
| [`../project-roadmap.md`](../project-roadmap.md) | Known issues / tech debt register (K-1 through K-10) |
| [`../../backend/docs/architecture-audit-2026-07-08.md`](../../backend/docs/architecture-audit-2026-07-08.md) | Backend architecture audit (findings F-CRIT-1 through F-HIGH-10) |
| [`../../standards/security.md`](../../standards/security.md) | Security baseline |
| [`../../standards/performance.md`](../../standards/performance.md) | Performance baseline |

## Logging

- Structured logs via `backend/app/core/logging.py`.
- Health/metrics: `GET /health`, `GET /metrics`, `GET /health/queue`.
- Log-grep cheatsheet: see [`chatbot-response-path.html`](chatbot-response-path.html) §"Log-grep cheatsheet".
