---
id: OPS-10
title: "Every image is a mutable tag and no digest is pinned anywhere"
severity: high
area: ops
labels: [ops, reliability]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# OPS-10 — Every image is a mutable tag and no digest is pinned anywhere

**Severity:** high · **Area:** ops · **Effort:** S · **Labels:** ops, reliability

**Trạng thái:** QA_TESTED

## Problem

All base images and all eight application services resolve through mutable tags, and the restore path pulls `latest` by default. No digest pin exists in either Dockerfile or in compose, so an unattended pull can change the runtime under a frozen application version.

## Evidence

- `backend/docker-compose.yml:7` `pgvector/pgvector:pg16`, `:19` `redis:7-alpine`, `:224` `adminer:4`, `:235` `caddy:2`; `frontend/Dockerfile:5,13` `node:22-alpine` + `nginx:1.27-alpine`; `backend/Dockerfile:2` `python:3.12-slim`.
- `backend/docker-compose.yml:34,59,84,131,147,168,195,213` — all 8 application services use `${IMAGE_TAG:-latest}`.
- `scripts/restore-droplet.sh:88` — the restore path is exactly the unattended pull that can change the runtime under a frozen application version (see OPS-02).

## Impact

An unattended pull can silently change the runtime under a frozen application version, and base-image CVEs cannot be patched predictably because there is no periodic rebuild or pin cadence.

## Suggested fix

Pin base images by digest in `backend/docker-compose.yml`, `frontend/Dockerfile` and `backend/Dockerfile`; make `IMAGE_TAG` a required variable (`${IMAGE_TAG:?}`) so no code path can silently resolve `latest`; add a scheduled Dependabot/Renovate PR for the digests.

## Notes

Merge with OPS-02 — the same missing `IMAGE_TAG` guard.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
