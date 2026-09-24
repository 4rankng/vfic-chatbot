---
id: OPS-20
title: "Low-severity restore, backup, dev-exposure, release-gate and migration-naming hygiene"
severity: low
area: ops
labels: [ops, security]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# OPS-20 — Low-severity restore, backup, dev-exposure, release-gate and migration-naming hygiene

**Severity:** low · **Area:** ops · **Effort:** S · **Labels:** ops, security

**Trạng thái:** IN_PROGRESS

## Problem

Five low-severity defects share one theme: the local tooling hides its own failures. `make restore` mutates a restored DB and resets every password, `make backup` leaves droppings, the dev compose file exposes Postgres and Adminer on all interfaces, `release-check` cannot detect the lockfile-drift class, and migration filenames no longer match their revision IDs.

## Evidence

- `Makefile:113-125` — `make restore` drops and recreates `vfic`, loads the dump with `ON_ERROR_STOP` left at psql's default (unlike `scripts/restore-droplet.sh:113`, which sets `-v ON_ERROR_STOP=0` explicitly), runs `alembic stamp head 2>/dev/null || true`, then `scripts.reset_passwords --password admin123` for **all** users.
- `Makefile:83-95` — the dump is written to `/tmp/` and removed only on the success path, historical `vfic_pg_backup_*.sql.gz` are never pruned, plain-SQL format (no `-Fc`) prevents parallel or selective restore, and `docker exec vfic-postgres-1` (`:85`) is hardcoded to the `/opt/vfic` compose project name.
- `backend/docker-compose.dev.yml:10` (`ports: ["5432:5432"]`) and `:34` (`8082:8080`) bind `0.0.0.0` with credentials `vfic/vfic` (`:8-9`) and a passwordless Redis on `6382` (`:13-16`), while `backend/docker-compose.yml:226` correctly binds Adminer to `127.0.0.1:8081`.
- `Makefile:16-19` — `release-check` checks a clean worktree, `git diff --check` and exactly one alembic head, but never lockfile consistency (`uv lock --check`, `npm ci` vs `npm install`); `frontend/Makefile:9-10`'s `install` uses `npm install` while `frontend/Dockerfile:9` and `.github/workflows/quality-gates.yml` use `npm ci`.
- `backend/alembic/versions/0030_delivery_status_send_unknown.py:22` declares `revision = "0030_send_unknown"`, `0031_conversation_seq_and_trace_id.py:28` declares `"0031_conversation_seq_trace"`, two files share the `0013_` prefix (`0013_password_reset_otps.py`, `0013_proactive_followup.py`, joined by `091e7edc9f76_merge_0013_password_reset_otps_0013_.py:12-13`), and `docs/deployment-guide.md:296-300` asks for ≤32-char revision IDs while `0053_single_page_external_source_sync_state` is 41.

## Impact

A partially failed local restore is reported as success, and a well-known password (`admin123`) is sprayed across every account if the restore is ever pointed at a shared environment; failed backup downloads accumulate on the droplet; anyone on an untrusted LAN can read the dev database, which is typically a copy of production data; the one gate that runs before a push cannot see the dependency-drift class; and `grep revision = "0031_conversation_seq_and_trace_id"` finds nothing, so filename-to-`alembic_version` correlation is unreliable.

## Suggested fix

Warn before the password reset in `Makefile:113-125` and fail the target when psql reports an error; use `mktemp` plus a trap, `pg_dump -Fc -Z6`, retention of the last N dumps, and `docker compose ps -q postgres` instead of the literal container name; bind the dev ports to `127.0.0.1:` and set a dev `REDIS_PASSWORD`; add `uv lock --check` to `release-check` and switch `frontend/Makefile:9-10` to `npm ci`; and enforce filename == revision ID with a check, renaming the two drifted revisions.

## Notes

Merge with OPS-05 (lockfile policy), OPS-16 (`stamp head`) and OPS-03 (restore correctness) when touching the same targets.

## Evidence log

- Landed: ON_ERROR_STOP restore, password-reset prompt (FORCE=1), mktemp+trap, -Fc -Z6 + pg_restore, compose-resolved containers, retention of 10, loopback dev ports, uv lock --check, npm ci
- REMAINING: the filename==revision check (+ the two drifted revisions) — alembic/versions is approval-gated; renaming IDs would break deployed alembic_version rows
- Decision: no dev Redis password — loopback binding is the control (e2e harness pins a passwordless URL); documented in docker-compose.dev.yml

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
