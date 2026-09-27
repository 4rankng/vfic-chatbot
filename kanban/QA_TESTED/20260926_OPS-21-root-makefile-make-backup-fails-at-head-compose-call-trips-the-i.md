---
id: OPS-21
title: "Root Makefile `make backup` fails at HEAD: compose call trips the ${IMAGE_TAG:?} guard"
severity: high
area: ops
labels: [ops, backup, regression]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-26
---

# OPS-21 — Root Makefile `make backup` fails at HEAD: compose call trips the ${IMAGE_TAG:?} guard

**Severity:** high · **Area:** ops · **Effort:** S · **Labels:** ops, backup, regression

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The wave-1 fix for `make backup` (replacing the hardcoded `docker exec vfic-postgres-1` with `docker compose ps -q postgres`) collided with the OPS-10 hardening that made IMAGE_TAG a required variable in every app image. On the droplet, /opt/vfic/.env does not define IMAGE_TAG (prod-env.sh never writes it), so any compose command without an explicit IMAGE_TAG env fails interpolation. `docker compose ps -q postgres` therefore errors, PG is empty, and the target aborts with 'compose reports no postgres container' before any dump is taken.

## Evidence

- Makefile:113-116 — backup's remote step runs `docker compose ps -q postgres` on the droplet with no IMAGE_TAG, then errors `compose reports no postgres container`
- backend/docker-compose.yml:103,139,167,212,239,267,297,327,363,441,454 — every app image is `${IMAGE_TAG:?IMAGE_TAG is required — the deploy passes the git sha}`; compose interpolates the whole file for every subcommand, including ps/start/logs
- backend/scripts/prod-env.sh:30-99 — the generated /opt/vfic/.env heredoc contains no IMAGE_TAG, so compose auto-load cannot satisfy the guard either
- backend/scripts/backup-droplet.sh:42-45 — the repo's own comment: 'The prod compose file requires IMAGE_TAG for EVERY subcommand' — which is why that script resolves the tag from the running container first
- Makefile:78 — `deploy-backend: release-check backup`, so the broken backup also blocks the backend-only deploy path

## Impact

The documented primary DB backup fails 100% of the time, and `make deploy-backend` fails with it — DB backups silently stop existing and backend-only deploys are blocked. Same root cause breaks `make deploy-status` (backend/Makefile:140), all three `profile-backfill-*` targets (:143-150 — bg_deploy.sh step 9b prints 'Status: make -C backend profile-backfill-status' after every deploy), and `make adminer` (:175, masked by `|| true`).

## Suggested fix

In the root Makefile backup target, resolve the tag on the droplet before composing (`docker inspect -f '{{.Config.Image}}'` on the active web container, then `IMAGE_TAG=$TAG docker compose ps -q postgres` — the pattern backup-droplet.sh:47-67 already uses). Sweep the sibling no-tag call sites in the same pass: backend/Makefile:140 (deploy-status), :144 (profile-backfill-run's inner compose ps), :147/:150 (profile-backfill-status/logs), :175 (adminer).

## Notes

The wave-1 card (tickets_d.py) recommended the compose call that now breaks — the fix landed without the IMAGE_TAG guard in scope. Differs from the held 'droplet backup/restore rehearsal' and 'bundle-zip pruning' items.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
