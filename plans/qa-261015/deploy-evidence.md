# Deploy evidence — 2026-10-15, tag 5cd91615 (bot.tingting.vip)

Deploy authorized in the task instruction ("USER-AUTHORIZED deploy code fix").
Rollback path: `make -C backend rollback` (flips Caddy to the previous
color/tag, previous image tags retained on the host).

## Gates before deploy (all green)

- `make release-check` — backend lane exit 0 (ruff w/ BLE, pyright app/graph
  0 errors, unit suite 3946 passed / 28 skipped, coverage TOTAL 80.9% ≥ 75
  floor); frontend lane exit 0; data lane exit 0 (migration roundtrip walk,
  golden RAG gate 100.0%, changed-surface integration lane 6 passed).
  Full log: `plans/qa-261015/release-check.log`.
- Red/green proof per fix: reverting each source fix (git stash) fails its new
  tests with the exact production error class; restoring goes green.

## Deploy (`make deploy-backend`, log excerpt retained in this file's section below)

- Backup lane exit 0 (prod pg dump + env snapshot), backend image
  `ghcr.io/4rankng/tinghire-be:5cd91615` built and pushed (buildx AMD64).
- Blue/green cutover: web-green created at 5cd91615, healthy 4/4 workers,
  smoke gate passed BEFORE the Caddy flip:

  ```
  SMOKE OK [single-message]: outcome='sent'
  SMOKE OK [progressive-send]: outcome='sent'
  SMOKE OK [progressive-send-failure]: outcome='error'   (deliberate failure-path probe)
  SMOKE OK [support-oa-hotline]: outcome='sent'
  SMOKE OK [support-oa-clarify]: outcome='sent'
  ```

- Caddy flipped blue → green; old web-blue drained and stopped.
  `bg_deploy done. active=web-green tag=5cd91615`.

## Post-deploy verification (each = live command on the server)

| Check | Result |
|---|---|
| Edge health | `curl https://bot.tingting.vip/health` → HTTP 200, `{"status":"ok","env":"production"}` |
| Scheduler set | zset `rq:scheduler:scheduled_jobs` 8 → 4 entries; all four dead ticks purged by the boot guard (external_source_sync ×2, proactive_followup, decision_trace_retention); only live ticks remain |
| Dead-tick errors | maintenance logs since deploy: 0 `external_source` / `proactive_followup` / `decision_trace` lines (was 8/day) |
| Recovery tick | `Successfully completed run_knowledge_recovery_tick ... 0:00:00.478268s` — first success since 2026-10-11; manual re-run `2a5730b1…` completed 0.88 s; `knowledge recovery sweep recovered: {'training_batches': 23, ...}`; zero `coroutine … has no attribute` errors since deploy (was 48/day) |
| Orphan backlog | `SELECT … FROM knowledge_category_revisions WHERE created_at < now()-3d AND status IN ('STAGED','PROCESSING')` → 0 rows (the review's 13-day-old backlog is gone) |
| MissingGreenlet | web-green logs since boot: 0 occurrences (was ~6/day) |
| /metrics counters | `realtime_payload_failures_total=0`, `realtime_publish_failures_total=0`, `knowledge_recovery_failures_total=0`, `workers=12` |
| Round-trip after ALL changes | re-ran `docker compose exec -T web-green python -m scripts.smoke_turn` post-postgres-recreate: 5/5 SMOKE OK, exit 0 |
| Container fleet | 15/15 running, 14 healthy (metrics-watch has no healthcheck — pre-existing, filed) |

## Finding 5 — Postgres memory (executed LAST)

- Headroom verified first: host 3915 MiB total, 2013 MiB available at
  decision time; worst-case limit sum with a 768M postgres stays within the
  host with ~1.9 GiB spare.
- Durable change: `backend/docker-compose.yml` postgres limit 448M → 768M
  (commit 0914b513, ledger comment updated), synced to
  `/opt/vfic/docker-compose.yml` (same file the deploy flow owns).
- Applied: `IMAGE_TAG=5cd91615 docker compose up -d postgres` → container
  recreated, `Up (healthy)`, `HostConfig.Memory = 805306368` (= 768 MiB).
- App connectivity: app session present in `pg_stat_activity`, in-container
  `/health` ok, edge 200, full smoke round-trip green after the restart.
- Rollback: revert commit 0914b513, re-sync compose, `docker compose up -d
  postgres` (same procedure, ~30 s outage window as observed).

## Rollback plan (code)

`make -C backend rollback` — flips Caddy back to the previous color/tag
(`PREV_COLOR`/`PREV_TAG` written by bg_deploy; previous image
`e74355be` retained on host and in GHCR). The boot-time dead-tick purge and
/metrics additions are inert without the new code path.

## Not covered

- Git push to origin (not part of the authorized deploy; commits live on
  local main: f8e1c5dd, 8472bc2b, 2b32ffaf, a0c7471e, b67ee6e4, 5cd91615,
  0914b513 + docs commit).
- ops-alerts.sh cron installation on the droplet (recommended by the review,
  outside this task's scope; the script now polls the new counters once
  installed).
- The 9 pre-existing manual-lane integration failures (classified + filed:
  `plans/qa-261015/integration-baseline-failures.md`).
- Long-run memory observation of the 768M ceiling (single post-change
  snapshot only).
