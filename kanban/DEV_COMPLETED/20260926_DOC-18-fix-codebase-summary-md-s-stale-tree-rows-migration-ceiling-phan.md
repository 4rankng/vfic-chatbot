---
id: DOC-18
title: "Fix codebase-summary.md's stale tree rows: migration ceiling, phantom graph/tools.py, 13-service enumeration"
severity: low
area: docs
labels: [documentation, tech-debt]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-26
---

# DOC-18 — Fix codebase-summary.md's stale tree rows: migration ceiling, phantom graph/tools.py, 13-service enumeration

**Severity:** low · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt

**Trạng thái:** DEV_COMPLETED

## Problem

Three rows in the repository map predate the post-sweep changes: the migration ceiling, a key-file that no longer exists (split into the graph/tools/ package with TOOL_SCHEMAS moved to schemas.py), and a prod-service enumeration that never included the metrics-watch service the compose file runs unconditionally.

## Evidence

- docs/codebase-summary.md:40 — 'alembic/ Hand-written migrations through 0054'; 0055_memories_match_halfvec.py exists and revises 0054 (deployment-guide.md:242 correctly names 0055)
- docs/codebase-summary.md:178 — key-files row '`backend/app/graph/tools.py` | `TOOL_SCHEMAS` + `_dispatch_tool`'; no tools.py exists — tools live in the tools/ package and TOOL_SCHEMAS/_dispatch_tool live in graph/schemas.py:27/:269, as the same doc's module map already states — the table contradicts the map one screen above
- docs/codebase-summary.md:46,:200 — '13-service prod stack' enumeration omitting metrics-watch; docker-compose.yml:362-437 defines metrics-watch always-on (only oa-profile-backfill at :438-440 is profile-gated), making 14 always-on services; TECH.md:59 repeats the 13 count
- docs/codebase-summary.md:4 — 'Last updated: 2026-09-24'; the tools/ split, migration 0055 and metrics-watch all landed after that date

## Impact

codebase-summary.md is AGENTS.md's 'Repository map' source of truth. The phantom tools.py row sends readers to a 404 and hides the domain split; the service miscount makes `docker compose ps` (14 running) disagree with the ops docs — exactly the confusion a responder doesn't need mid-incident.

## Suggested fix

Bump :40 to 'through 0055' (or point at deployment-guide's CI-guarded HEAD line); rewrite the :178 row to graph/schemas.py and add a tools/ row naming the per-domain modules; correct :46/:200 and TECH.md:59 to 14 always-on services + the profile-gated oa-profile-backfill, adding metrics-watch to the enumeration. Refresh the 'Last updated' stamp.

## Notes

Verify with `git diff HEAD -- backend/docker-compose.yml` before fixing the count: metrics-watch may be part of the uncommitted incident response (OPS-25) — if so the docs correction lands with that commit.

## Evidence log

- docs/codebase-summary.md tree/key-files rows fixed: migration ceiling to 0056, phantom graph/tools.py and safety.py rows replaced with the real module map, service enumeration corrected to 14 always-on services (metrics-watch always-on, oa-profile-backfill profile-gated) — verified against docker-compose.yml; TECH.md:59 count updated to match.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
