---
type: operations
title: Blue/green deployment topology and release gate
description: How the production stack ships via manual blue/green cutover, why Caddy never routes to a broken image, and what the local release-check gate enforces before any image is pushed.
tags: [deployment, blue-green, caddy, release-check, smoke-gate, docker, zero-downtime]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
sources:
  - id: openwiki-source-c1f81dc12181334bf105db16
    resource: repo://backend/Caddyfile.template
  - id: openwiki-source-3641e44aef067384d4965781
    resource: repo://backend/docker-compose.yml
  - id: openwiki-source-d90fca79839a07479341ddb0
    resource: repo://backend/Makefile
  - id: openwiki-source-fa1d9591fcc1f4e1672f652e
    resource: repo://backend/scripts/bg_deploy.sh
  - id: openwiki-source-af0d70ef064f90ef3be7a8ab
    resource: repo://backend/scripts/bg_rollback.sh
  - id: openwiki-source-1e8c818630ff949250d0742f
    resource: repo://backend/scripts/flip_caddy.sh
  - id: openwiki-source-7865fb2b5570e6ebb2f50ca8
    resource: repo://docs/deployment-guide.md
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "opencode", at: "2026-09-21T02:42:43.794Z" }
---

Production runs on a single DigitalOcean droplet (`bot.tingting.vip`, 2 vCPU
/ ~4 GB RAM) with Docker Compose at `/opt/vfic`. Deployment is **manual**,
driven from a developer Mac over SSH with `ControlMaster` multiplexed
connections; there is **no CI deploy to production**. The cutover is a true
zero-downtime blue/green swap: the new color is health- and smoke-checked
before Caddy is flipped onto it, and a failed smoke gate aborts with the old
color still serving.

## Stack topology

`backend/docker-compose.yml` ships to `/opt/vfic` and auto-loads
`/opt/vfic/.env`. Images are pulled from GitHub Container Registry
(`ghcr.io/4rankng/inghire-be` and `ghcr.io/4rankng/inghire-fe`):

- `ghcr.io/4rankng/tinghire-be:<git-sha>` — immutable, what `make deploy`
  uses (`IMAGE_TAG ?= $(GIT_SHA)` from the short git sha).
- `ghcr.io/4rankng/tinghire-be:latest` — registry convenience tag only,
  never used by the deploy script.
- `ghcr.io/4rankng/tinghire-fe:<git-sha>` — nginx static SPA.

| Service | Image / base | Replicas | Role |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 1 | `max_connections=150`, healthcheck `pg_isready`, volume `vfic_pgdata`. |
| `redis` | `redis:7-alpine` | 1 | RQ broker + pub/sub + LLM semaphore/cache. AOF on, 256 MB cap `allkeys-lru`, volume `vfic_redisdata`. |
| `web-blue` / `web-green` | `ghcr.io/4rankng/tinghire-be:${IMAGE_TAG:-latest}` | 1 each (only active receives traffic) | FastAPI (uvicorn, 1 worker). Expose 8000. Volume `vfic_kb_uploads`. Healthcheck `python urllib /health`. |
| `worker-chatbot` | `ghcr.io/4rankng/tinghire-be:<tag>` | 2 | RQ queue `webhook_high` only. Chatbot imports and LLM clients warmed at boot. 180 s `stop_grace_period`, 512 MB limit. |
| `worker-persistence` | `ghcr.io/4rankng/tinghire-be:<tag>` | 1 | RQ queue `persistence_low` only. Best-effort enrichment isolated from candidate replies. 512 MB limit. |
| `worker-ingest` | `ghcr.io/4rankng/tinghire-be:<tag>` | 1 | RQ queue `ingest`. Mounts `vfic_kb_uploads`. |
| `worker-followup` | `ghcr.io/4rankng/tinghire-be:<tag>` | 1 | RQ queue `followup`. Low proactive volume → single replica. |
| `scheduler` | `ghcr.io/4rankng/tinghire-be:<tag>` | 1 | `rqscheduler`. |
| `frontend` | `ghcr.io/4rankng/tinghire-fe:<tag>` | 1 | nginx static SPA. Expose 80. |
| `adminer` | `adminer:4` | 1 | DB UI, bound to `127.0.0.1:8081` (loopback only; reach via `make adminer` SSH tunnel). |
| `caddy` | `caddy:2` | 1 | Edge. `80:80`, `443:443`. Caddyfile RO, regenerated from template. |

Volumes: `vfic_pgdata`, `vfic_redisdata`, `vfic_caddy_data`,
`vfic_caddy_config`, `vfic_kb_uploads`.

## Blue/green web tier

`web-blue` and `web-green` are identical replicas; **only the active color
receives traffic**. The active color is tracked in `/opt/vfic/ACTIVE_COLOR`;
Caddy's upstream is rendered from `backend/Caddyfile.template` with
`__WEB_UPSTREAM__` substituted to `web-<active>:8000` by
`scripts/flip_caddy.sh`. The Caddyfile on disk is regenerated on every
flip — never hand-edit `/opt/vfic/Caddyfile`.

### Edge routes (`Caddyfile.template`)

| Path | Upstream | Notes |
|---|---|---|
| `/webhooks/*` | `__WEB_UPSTREAM__:8000` | Channel adapters (Zalo Bot, Zalo OA) |
| `/health` | `__WEB_UPSTREAM__:8000` | Public liveness — backend JSON, not the SPA |
| `/api/*` | `__WEB_UPSTREAM__:8000` | All REST routes |
| `/realtime/*` | `__WEB_UPSTREAM__:8000` | SSE firehose, `flush_interval -1` so events flush immediately |
| `/socket.io/*` | `__WEB_UPSTREAM__:8000` | Socket.IO websocket upgrade; `reverse_proxy` upgrades transparently |
| `/*` (catch-all) | `frontend:80` | React Admin SPA |

Headers set globally: `Strict-Transport-Security: max-age=31536000; includeSubDomains`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
Encoding: `zstd gzip`.

## Deploy sequence

`backend/scripts/bg_deploy.sh` runs **on the droplet** with
`IMAGE_TAG=<git-sha>` in the environment:

1. `docker pull ghcr.io/4rankng/tinghire-be:$IMAGE_TAG`.
2. Ensure `postgres` and `redis` are up (`--wait`).
3. One-shot Alembic migration on a transient web-blue container
   (`alembic upgrade head`).
4. Bring up the **inactive** web color + all workers at the new image tag.
5. Wait for the new color's Docker healthcheck (`python urllib /health`,
   `start_period: 30s` designed to absorb the single-worker cold-boot
   fork window).
6. **Smoke gate** — `docker compose exec -T web-<NEXT> python -m scripts.smoke_turn`
   runs one real bot turn. If it fails, the script exits BEFORE the flip.
7. `scripts/flip_caddy.sh <NEXT>` — render Caddyfile from template,
   `caddy validate` (warns and reloads anyway if `validate` is unavailable),
   `caddy reload` (graceful, <1s, no dropped connections).
8. Record `PREV_COLOR` and `PREV_TAG` for `make rollback`.
9. `docker compose stop` the old color. The container is **kept** (not
   removed) so rollback can revive it instantly.
10. Inaugural deploy only: remove the legacy single-`web` container.

The post-flip readiness check (`verify_post_flip_readiness` in
`bg_deploy.sh`) confirms the active color has exactly one running container
that is healthy and has not restarted, and that the rendered Caddyfile
references `web-<NEXT>:8000`.

## Rollback

`make rollback` (driven from `backend/Makefile`) SCPs `bg_rollback.sh` and
`flip_caddy.sh`, then SSHes `bash scripts/bg_rollback.sh`. The rollback
reads `PREV_COLOR` and `PREV_TAG`, brings the previous color back up at its
recorded tag, re-flips Caddy, and rolls back the ACTIVE_COLOR pointer. No
rebuild is required — the previous image is already on the droplet.

## Per-worker replica counts

The replica counts are intentional and tied to specific behaviors:

- **`worker-chatbot` ×2** — runs the `webhook_high` queue. Each replica warms
  chatbot imports and LLM clients at boot; two replicas absorb a webhook
  burst without dropping to the persistence queue. 180 s
  `stop_grace_period` covers an in-flight turn that started before SIGHUP.
- **`worker-persistence` ×1** — runs the `persistence_low` queue. Best-effort
  lead / memory enrichment that must never delay a candidate reply. Isolated
  so a slow persistence job cannot back-pressure the chat path.
- **`worker-ingest`, `worker-followup`, `scheduler` ×1 each** — low-volume
  queues; a single replica is enough and avoids cross-replica locking on
  the same RQ job.

## Release gate

`make release-check` (root `Makefile`) is the precondition that must pass
locally before any image is pushed. It runs:

1. `git status --porcelain` — must be empty (release blocked otherwise).
2. `git diff --check`.
3. `cd backend && .venv/bin/python -m alembic heads | wc -l` must equal `1`
   (no migration branches left dangling).
4. `cd backend && docker compose -f docker-compose.dev.yml up -d --wait postgres redis`
   then `ruff check .`, `pytest -m "not integration"`,
   `pytest -m integration tests/integration/test_harness_smoke.py`.
5. `cd frontend && npm run lint && npm run typecheck &&
   npm run test:unit:app -- --run &&
   npm run test:unit:app:coverage:changed-surface -- --run &&
   npm run build &&
   npm run test:e2e:desktop &&
   npm run test:e2e:mobile`.
6. RAG golden benchmark: `backend/scripts/benchmark_rag.py --gold --min-pass-rate 0
   --output <raw>` writes a JSON artifact; an inline script extracts
   `passed / case_count` into a golden file, and
   `backend/scripts/release_gate_check.py --golden-results <golden>` is the
   pass/fail gate.

If any gate fails, `make deploy` aborts. The release gate is intentionally
additive: lint, typecheck, unit, integration smoke, E2E desktop + mobile,
plus a RAG quality regression check.

## What this contract guarantees

- **Zero-downtime cutover.** Until step 7 the old color is still serving;
  the smoke gate (step 6) is a binary go/no-go.
- **Smoke gate before flip.** A bad image never receives a single public
  request — the script exits before `flip_caddy.sh` runs.
- **Instant rollback.** The previous image is on the droplet, the inactive
  container is kept, and `make rollback` flips back in seconds without a
  rebuild.
- **Immutability.** Deploys are pinned to `<git-sha>`. `latest` is a
  convenience tag and is **never used by `make deploy`**.
- **Hand-edit immunity.** The shipped Caddyfile is regenerated from
  `Caddyfile.template` on every flip, so manual edits to
  `/opt/vfic/Caddyfile` are wiped.

## Operational notes

- `make deploy-status` (over SSH) prints `ACTIVE_COLOR`, `PREV_COLOR`,
  `PREV_TAG`, and `docker compose ps`.
- `make profile-backfill-run` is a one-off `oa-profile-backfill` job
  (gated by a maintenance profile) that backfills missing Zalo OA profile
  names/avatars after a successful cutover.
- `make deploy-breaking` accepts brief downtime for non-additive Alembic
  migrations and is gated on operator intent.
- The same `Makefile` builds both `backend` and `frontend` images
  (`make push` in each subproject) before the SSH handoff.
