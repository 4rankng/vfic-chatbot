---
id: OPS-09
title: "Memory limits cover 3 of 12 services and the documented host size contradicts itself"
severity: high
area: ops
labels: [ops, reliability]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# OPS-09 — Memory limits cover 3 of 12 services and the documented host size contradicts itself

**Severity:** high · **Area:** ops · **Effort:** S · **Labels:** ops, reliability

**Trạng thái:** IN_PROGRESS

## Problem

Only `worker-chatbot`, `worker-persistence` and `oa-profile-backfill` declare `deploy.resources.limits.memory`; the other nine services — including `postgres`, `worker-ingest`, both web colours and `caddy` — are unbounded. Host RAM is documented as 4 GB in two places but as 2 GB and 1.9 GiB in two others.

## Evidence

- `backend/docker-compose.yml:86-97` (`worker-chatbot`, 512M × `replicas: 3`), `:118-121` (`worker-persistence`, 512M), `:212-217` (`oa-profile-backfill`, 512M) — the only three limits; `web-blue`, `web-green`, `postgres`, `worker-ingest`, `worker-followup`, `scheduler`, `frontend`, `caddy` and `adminer` have none.
- `TECH.md:94` and `docs/deployment-guide.md:4` say **4 GB**; `backend/docker-compose.yml:92-96` says "the **2GB** droplet … host headroom verified at deploy time"; `backend/Dockerfile:25-28` says "the **1.9GiB** host".
- `backend/docker-compose.yml:8` tunes only `max_connections=150`, not memory, and `postgres` declares no `shm_size`, leaving `/dev/shm` at Docker's 64 MB default; `redis` is bounded only by `--maxmemory 256mb` (`:21`).
- `backend/scripts/bg_deploy.sh:120-135` verifies container counts but never that limits were applied. [INFERENCE] Docker Compose v2 honouring `deploy.replicas`/`deploy.resources.limits` is assumed — the repo's own tests and `declared_replicas` depend on it — and the limits were not verified at runtime.

## Impact

Declared caps sum to ≈2.0 GB; add PostgreSQL's default `shared_buffers` (~25% of RAM) plus `worker-ingest` embedding bursts and the resident non-limited services and the box is oversubscribed. A single runaway `worker-ingest` can trigger the OOM killer against Postgres or Caddy — an unbounded-blast-radius outage — and `max_connections=150` with a 64 MB `/dev/shm` invites the classic "could not resize shared memory segment" errors.

## Suggested fix

Set an explicit limit on every service in `backend/docker-compose.yml` with a documented sum that fits the real host size; fix the 4 GB / 2 GB / 1.9 GiB contradiction in one place; add `shm_size: 256mb` to `postgres`; and make `backend/scripts/bg_deploy.sh` verify `docker inspect .HostConfig.Memory` rather than only container counts.

## Notes

Merge with OPS-10 — both are single-pass fixes to the same compose file.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
