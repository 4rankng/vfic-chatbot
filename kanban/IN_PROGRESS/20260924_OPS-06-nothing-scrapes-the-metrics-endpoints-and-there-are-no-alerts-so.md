---
id: OPS-06
title: "Nothing scrapes the metrics endpoints and there are no alerts, so the only signal is the reconcile worker"
severity: high
area: ops
labels: [ops, reliability]
effort: M
status: in_progress
column: TODO
opened: 2026-09-24
---

# OPS-06 — Nothing scrapes the metrics endpoints and there are no alerts, so the only signal is the reconcile worker

**Severity:** high · **Area:** ops · **Effort:** M · **Labels:** ops, reliability

**Trạng thái:** TODO

## Problem

`/metrics` and `/health/queue` exist and export queue depths, worker counts and 9 reconcile counters, but Caddy does not proxy them and no scraper, uptime check or alert rule exists anywhere in the repo. Nothing in the system pages a human, so most failure classes are only noticed if someone happens to open the admin console.

## Evidence

- `backend/app/main.py:209-211` (`/health`), `:214-245` (`/metrics`: RQ queue depths + worker count + reconcile counters), `:247-257` (`/health/queue` via `backend/app/core/ops_health.py:12`); the 9 counters are defined at `backend/workers/reconcile_worker.py:27-36`.
- `backend/Caddyfile.template:17-50` — routes only `/webhooks/*`, `/health`, `/api/*`, `/realtime/*` and `/socket.io/*`; `/metrics` and `/health/queue` are not proxied, and `docs/deployment-guide.md:437-439` acknowledges they are internal-only.
- `docs/deployment-guide.md:444-446` — "**No external APM**. No Sentry/Datadog/OpenTelemetry." No scrape config, uptime check or alert rule exists in the repo.
- `backend/scripts/bg_deploy.sh:120-135` — the only consumer asserts queue-health keys *exist* at deploy time; nothing watches them afterwards.

## Impact

Nothing in the system pages a human. Detection times today:

| Failure | Detected by | Time to human awareness |
|---|---|---|
| Bot turn silently lost | `reconcile_worker` re-enqueues on the `recovery` queue, ~60s scan + 120s grace (`backend/workers/reconcile_worker.py:9-12`); no counter is alerted | recovery ~3-4 min, **notification: never** |
| Queue-depth growth / worker saturation | `/metrics`, `/health/queue` (chart only, shown via `api/dashboard.py`) | only if a human opens the console |
| DB connection exhaustion | pool timeout raises → 500s in logs | never proactively |
| LLM provider outage | provider failover + suppressed-turn log (`docs/deployment-guide.md:311-312`) | never proactively |
| Disk full | nothing | unbounded (OPS-04) |
| Wedged worker process | **not detected at all** (OPS-08) | never |

## Suggested fix

(a) An external uptime check on `https://bot.tingting.vip/health` with email/Telegram alerting; (b) a 1-minute cron on the droplet (or a GitHub Action) that curls `/metrics` and `/health/queue` inside the Docker network — `docker compose exec -T web-$(cat ACTIVE_COLOR) python -c …`, the pattern already documented at `docs/deployment-guide.md:333-336` — and alerts on `queue_depth > CHAT_QUEUE_MAX_DEPTH*0.5`, `busy_workers == total_workers` for N minutes, rising `reconcile_enqueue_failed_total`/`reconcile_unknown_send_outcome`, and disk > 80%; (c) expose `/metrics` through Caddy behind an allowlist only if a scraper needs it.

## Notes

Merge with OPS-04 (disk alert) and OPS-08 (wedged-worker signal).

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
