---
id: OPS-24
title: "frontend and caddy services have no healthcheck; the edge is only probed at deploy time"
severity: low
area: ops
labels: [ops, reliability, observability]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-26
---

# OPS-24 — frontend and caddy services have no healthcheck; the edge is only probed at deploy time

**Severity:** low · **Area:** ops · **Effort:** S · **Labels:** ops, reliability, observability

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

frontend (nginx SPA) and caddy (the edge) are the only long-running services without a healthcheck, so their Docker health status is permanently 'none' and bg_deploy's require_running_service_count can only assert the process exists, not that it serves. In-stack probing never covers them: metrics-watch polls the web colours directly on the compose network, and the only edge-level checks are the deploy-time curl and ops-alerts.sh's public curl — the latter cron-unwired (known hold) and broken internally (OPS-23).

## Evidence

- backend/docker-compose.yml:453-460 — frontend service: expose 80, memory limit, restart policy, no healthcheck key
- backend/docker-compose.yml:462-480 — caddy service: ports 80/443, Caddyfile mount, no healthcheck key (postgres/redis/web/workers/scheduler all carry one)
- backend/docker-compose.yml:362-412 — metrics-watch probes `http://<color>:8000/...` directly, never through caddy
- backend/scripts/bg_deploy.sh:224-227 — the only edge probe is deploy-time (`curl https://bot.tingting.vip/health` and `/` during verify_post_flip_readiness)

## Impact

A proxy serving 404s/502s or an nginx serving a stale/blank bundle runs 'healthy-looking' indefinitely; detection depends on the currently-nonfunctional ops-alerts path, so a wedged edge is found by users first.

## Suggested fix

Add `healthcheck` to frontend: `CMD wget -q --spider http://127.0.0.1/` (nginx ships wget). For caddy, probe the rendered listener (`wget -q --spider http://127.0.0.1:80`, accepting the 308) so a wedged edge shows unhealthy in `docker compose ps` and can gate bg_rollback's service checks.

## Notes

Kept low: static nginx rarely wedges, and caddy failure modes are usually port-level. Complements OPS-23 — together they close the edge-detection gap.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
