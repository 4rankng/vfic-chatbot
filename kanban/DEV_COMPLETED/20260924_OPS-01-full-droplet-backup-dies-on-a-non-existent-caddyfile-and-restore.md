---
id: OPS-01
title: "Full-droplet backup dies on a non-existent Caddyfile, and restore hard-requires the artifact it can never produce"
severity: critical
area: ops
labels: [ops, reliability]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# OPS-01 — Full-droplet backup dies on a non-existent Caddyfile, and restore hard-requires the artifact it can never produce

**Severity:** critical · **Area:** ops · **Effort:** S · **Labels:** ops, reliability

**Trạng thái:** IN_PROGRESS

## Problem

`make backup-full` copies `backend/Caddyfile` into the bundle at step 4 of 7, but that file does not exist — only `backend/Caddyfile.template` is tracked, and the production Caddyfile is generated on the droplet by `flip_caddy.sh`. Because the script runs under `set -euo pipefail`, the run aborts after the DB dump and the volume tarballs but before `zip`/`.zip.sha256`, so no artifact the runbook recognises is ever produced. `make restore-prod` then aborts at preflight on the very member the backup can never emit.

## Evidence

- `scripts/backup-droplet.sh:78` — `cp "$REPO_ROOT/backend/Caddyfile" "$BUNDLE/config-snapshot/Caddyfile"`, inside a script that sets `set -euo pipefail` at `:22`; no `backend/Caddyfile` exists, only `backend/Caddyfile.template`.
- `scripts/restore-droplet.sh:42` — `[ -f "$BUNDLE/config-snapshot/Caddyfile" ] || { echo "missing …"; exit 2; }`; `:80` uploads it as `/opt/vfic/Caddyfile`.
- `docs/DROPLET-BACKUP-RESTORE.md:27` — lists `config-snapshot/Caddyfile` as a required bundle member.
- `scripts/backup-droplet.sh:120-124` — `zip` and the `.zip.sha256` checksum run *after* the failing step, so a partially populated `backups/<ts>/` directory is all the operator gets.
- `backend/scripts/flip_caddy.sh:32-36` — the real production Caddyfile is *generated* on the droplet; `Makefile:134-136` (`backup-full`) and `Makefile:140` (`restore-prod`) are the entry points.

## Impact

The entire "delete the droplet, rebuild it later" disaster-recovery story is non-functional: `make backup-full` cannot emit a zip and `make restore-prod` cannot start even with a hand-built bundle. [INFERENCE] The pair has never been exercised — no restore rehearsal exists anywhere in `docs/`, `openwiki/` or `plans/` — though the missing `backend/Caddyfile` proves it cannot have succeeded recently.

## Suggested fix

Capture the *rendered* `/opt/vfic/Caddyfile` from the droplet (it is the real edge config and contains the active colour) with one `scp` beside the existing `.env` fetch, keeping `Caddyfile.template` as a second snapshot; wrap the three `cp` calls at `scripts/backup-droplet.sh:77-79` in existence guards that `die` with a clear message; and make `scripts/restore-droplet.sh` accept either `Caddyfile` or `Caddyfile.template` and regenerate via `flip_caddy.sh`. Then run the pair end-to-end against a throwaway droplet and record the date in `docs/DROPLET-BACKUP-RESTORE.md`.

## Notes

Merge with OPS-02 — both are defects in the same backup/restore pair, and the end-to-end rehearsal should close both at once.

## Evidence log

- Landed: backup-droplet.sh snapshots via guarded snapshot_file() and fetches the RENDERED /opt/vfic/Caddyfile (dies if empty/unflipped); restore accepts Caddyfile or Caddyfile.template
- BLOCKED: the card requires an end-to-end run against a throwaway droplet + a date in docs/DROPLET-BACKUP-RESTORE.md — no droplet access from here
- verified: bash -n on both scripts

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
