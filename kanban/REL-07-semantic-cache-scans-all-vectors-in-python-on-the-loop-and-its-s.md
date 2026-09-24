---
id: REL-07
title: "Semantic cache scans all vectors in Python on the loop, and its scope guard has a hole"
severity: medium
area: reliability
labels: [reliability, performance]
effort: M
status: todo
found: 2026-09-24
---

# REL-07 — Semantic cache scans all vectors in Python on the loop, and its scope guard has a hole

**Severity:** medium · **Area:** reliability · **Effort:** M · **Labels:** reliability, performance

## Problem

Every uncached lookup transfers and parses all stored vectors and compares them in pure Python on the event loop, and the scope guard keys on `project_slug`, which is `None` for Page-scoped conversations.

## Evidence

- `backend/app/graph/semantic_cache.py:97-118` — `HGETALL`, `json.loads` per entry, `_cosine` per entry (`:36-49`).
- `backend/app/core/config.py:201-205` — `semantic_cache_enabled=False`, capacity 200, dim 3072.
- `backend/app/graph/tools/knowledge.py:255,292` — the scope guard is `not project_slug`, but a Page-scoped conversation has `project_slug=None` with a non-empty `project_ids` (`backend/app/graph/factories.py:786-790`).

## Impact

Dormant today because the feature is off, so this is latent cost plus an enabled-day correctness hazard: roughly 12 MB transferred and ~600k interpreted float operations per lookup on a 2 vCPU box, and a cached answer computed against another Page's catalog could be returned.

## Suggested fix

Gate on `project_ids is None` rather than `project_slug` (or include the project scope in the key), store packed float16 with a lower capacity, and run the scan via `asyncio.to_thread`. If it will not be enabled, delete the call path rather than carrying an untested branch.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
