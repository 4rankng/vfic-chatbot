---
id: REL-07
title: "Semantic cache scans all vectors in Python on the loop, and its scope guard has a hole"
severity: medium
area: reliability
labels: [reliability, performance]
effort: M
status: todo
column: TODO
opened: 2026-09-24
---

# REL-07 — Semantic cache scans all vectors in Python on the loop, and its scope guard has a hole

**Severity:** medium · **Area:** reliability · **Effort:** M · **Labels:** reliability, performance

**Trạng thái:** TODO

## Problem

Every uncached lookup transfers and parses all stored vectors and compares them in pure Python on the event loop, and the scope guard keys on `project_slug`, which is `None` for Page-scoped conversations.

## Evidence

- `backend/app/graph/semantic_cache.py:129-148,168-171` — `HGETALL`, `json.loads` per entry, `_cosine` per entry (`:89-102`).
- `backend/app/core/config.py:245-248,46` — `semantic_cache_enabled=False`, capacity 200, dim 3072.
- `backend/app/graph/tools/knowledge.py:260,309` — the scope guard is `not project_slug`, but a Page-scoped conversation has `project_slug=None` with a non-empty `project_ids` (`backend/app/graph/factories.py:835-860`).

## Impact

Dormant today because the feature is off, so this is latent cost plus an enabled-day correctness hazard: roughly 12 MB transferred and ~600k interpreted float operations per lookup on a 2 vCPU box, and a cached answer computed against another Page's catalog could be returned.

## Suggested fix

Gate on `project_ids is None` rather than `project_slug` (or include the project scope in the key), store packed float16 with a lower capacity, and run the scan via `asyncio.to_thread`. If it will not be enabled, delete the call path rather than carrying an untested branch.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
