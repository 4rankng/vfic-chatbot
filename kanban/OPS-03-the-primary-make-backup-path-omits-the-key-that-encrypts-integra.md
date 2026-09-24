---
id: OPS-03
title: "The primary make backup path omits the key that encrypts integration credentials, so a restore silently yields undecryptable data"
severity: critical
area: ops
labels: [ops, security]
effort: S
status: todo
found: 2026-09-24
---

# OPS-03 — The primary make backup path omits the key that encrypts integration credentials, so a restore silently yields undecryptable data

**Severity:** critical · **Area:** ops · **Effort:** S · **Labels:** ops, security

## Problem

`make backup` dumps only `pg_dump` of `vfic` to OneDrive — no `.env` — yet every `integration_settings` row is sealed with AES-GCM under a key derived from `INTEGRATION_SETTINGS_ENCRYPTION_KEY` (with `JWT_SECRET` as fallback), and that key existed only in `/opt/vfic/.env`. On `InvalidTag` the service skips the row with a warning and callers fall back to env values, so a restore looks successful while silently discarding credentials.

## Evidence

- `backend/app/services/integration_settings.py:273-275` — `raw = self._settings.integration_settings_encryption_key or self._settings.jwt_secret; self._key = hashlib.sha256(raw.encode()).digest()`; sealing/opening at `:277-291` and `:293-306`.
- `backend/app/services/integration_settings.py:392-402` — on `InvalidTag` the row is skipped with a warning and callers fall back to env values; `:1140-1148` fails closed only for context-bound Page tokens.
- `Makefile:77-95` — `make backup` writes just the `pg_dump` to OneDrive; this is the documented primary backup (`docs/deployment-guide.md:359`) and a hard dependency of `deploy-backend` (`Makefile:54`).
- `Makefile:98-131` — `make restore` loads that dump into the **dev** DB, whose `.env` carries the dev `JWT_SECRET` (`.env.example:30`) and an empty `INTEGRATION_SETTINGS_ENCRYPTION_KEY` (`prod-env.sh:61`): a different key by construction.
- `docs/DROPLET-BACKUP-RESTORE.md:110-118` — discusses Postgres-password consistency across a restore but never mentions this key.

## Impact

Two distinct data-loss paths. (1) `make restore` into dev: every `integration_settings` row (Zalo bot token + webhook secret, MiniMax/OpenRouter keys, Facebook App secret/Page tokens) becomes `InvalidTag`, is logged as `integration setting decrypt failed … falling back to env`, and is discarded — the restore reports success. (2) If the droplet is lost and only the OneDrive dumps survive, production's sealed credentials are unrecoverable, because `INTEGRATION_SETTINGS_ENCRYPTION_KEY` (and the `JWT_SECRET` fallback) lived only in `/opt/vfic/.env`.

## Suggested fix

Treat `/opt/vfic/.env` as part of every backup — add it to `make backup` (`Makefile:77-95`), as `make backup-full` already does; document `INTEGRATION_SETTINGS_ENCRYPTION_KEY` as the DR-lost-secret and store it in a password manager separate from the droplet; add a post-restore assertion that decrypts one known integration row and fails loudly on `InvalidTag` instead of warning; and label the `jwt_secret` fallback at `backend/app/services/integration_settings.py:273-275` as a migration hazard, since rotating `JWT_SECRET` re-breaks every stored secret.

## Notes

Merge with OPS-01/OPS-02 — all three live in the same backup/restore path and should be rehearsed together.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
