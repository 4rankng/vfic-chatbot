---
id: ARCH-10
title: "`api/knowledge.py` calls private service methods, so the cutover guard is enforced at four call sites"
severity: medium
area: architecture
labels: [tech-debt]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# ARCH-10 — `api/knowledge.py` calls private service methods, so the cutover guard is enforced at four call sites

**Severity:** medium · **Area:** architecture · **Effort:** S · **Labels:** tech-debt

**Trạng thái:** IN_PROGRESS

## Problem

The router calls `KnowledgeService._require_version` and `KnowledgeService._require_legacy_mutation_allowed` directly, although the service already runs the same guards inside its own mutation methods. The guard is a precondition of the mutation, not an HTTP concern.

## Evidence

- `backend/app/api/knowledge.py:129,175,176,397,420` — the router's calls to the two underscore methods.
- `backend/app/services/knowledge/service.py:205,253,339,370,476,504,521,542` — the same guards already run inside `ingest_version`/`ingest_document` and the other mutation methods, so the router calls are duplication.
- `backend/app/services/knowledge/service.py:652-655` — the cutover rule being guarded ("Project-owned knowledge is exclusive to its selected mode").

## Impact

The cutover rule is enforced at four call sites instead of one, so any new mutation path that forgets the underscore call silently bypasses the migration guard.

## Suggested fix

Delete the two router calls — the private guards already run inside `ingest_version`/`ingest_document`. If a route genuinely needs to validate before enqueueing, expose a public `assert_mutable(project_id)` and call that; never the underscore name.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
