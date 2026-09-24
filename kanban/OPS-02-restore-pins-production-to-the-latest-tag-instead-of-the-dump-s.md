---
id: OPS-02
title: "Restore pins production to the latest tag instead of the dump's recorded image tag and never verifies schema compatibility"
severity: critical
area: ops
labels: [ops, reliability]
effort: M
status: todo
found: 2026-09-24
---

# OPS-02 — Restore pins production to the latest tag instead of the dump's recorded image tag and never verifies schema compatibility

**Severity:** critical · **Area:** ops · **Effort:** M · **Labels:** ops, reliability

## Problem

`scripts/restore-droplet.sh` runs `docker compose pull` and `docker compose up -d` with `IMAGE_TAG` unset, so compose resolves `${IMAGE_TAG:-latest}` — the tag that is re-pushed on every deploy, not the tag that produced the dump. The bundle *does* record the running images in `manifests/docker-images.txt`, but nothing reads it. The script also skips `alembic upgrade head` on the grounds that "the dump already has schema@head" and never checks that the restored `alembic_version` matches the revision the pulled image expects.

## Evidence

- `scripts/restore-droplet.sh:88` (`docker compose pull`) and `:132` (`docker compose up -d`) — neither exports `IMAGE_TAG`, so compose falls back to `${IMAGE_TAG:-latest}` at `backend/docker-compose.yml:44, 131, 147, 168, 195, 213, 84`.
- `scripts/backup-droplet.sh:88-89` — writes `manifests/docker-images.txt` into the bundle; no reader for it exists anywhere in `scripts/`.
- `scripts/restore-droplet.sh:8-12` — explicitly skips `alembic upgrade head` ("the dump already has schema@head") with no assertion against the image's expected head.
- `backend/Makefile:100` and `frontend/Makefile:70` — `latest` is re-pushed on every deploy, so "restore a backup from 3 weeks ago" means new code against old schema.
- `web-blue`/`web-green` carry no `IMAGE_TAG` default guard, so a bare `docker compose up -d` on the droplet (reboot, manual fix, `backend/scripts/flip_caddy.sh:38`) silently drifts off the tag recorded in `/opt/vfic/ACTIVE_COLOR`.

## Impact

A restored production can run code newer or older than the dumped schema, producing exactly the failure modes the blue/green flow exists to prevent: mid-turn `UndefinedColumn` errors, wrong enum semantics, or a bot that boots healthy and crashes on the first write.

## Suggested fix

Have `scripts/restore-droplet.sh` read the tag from `manifests/docker-images.txt` (falling back to an explicit `--tag`), export `IMAGE_TAG` for every `docker compose pull`/`up` invocation, then run `python -m scripts.widen_alembic_version && alembic upgrade head` and assert `alembic current` equals the image's head before declaring success. Also fail closed on the droplet when `ACTIVE_COLOR`'s tag differs from the running container's image tag.

## Notes

Merge with OPS-10 — the same missing `IMAGE_TAG` guard is what lets the restore pull `latest`.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
