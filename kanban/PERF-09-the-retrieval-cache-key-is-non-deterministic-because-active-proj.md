---
id: PERF-09
title: "The retrieval cache key is non-deterministic because `active_project_ids()` has no ORDER BY"
severity: medium
area: performance
labels: [performance, reliability]
effort: S
status: todo
found: 2026-09-24
---

# PERF-09 — The retrieval cache key is non-deterministic because `active_project_ids()` has no ORDER BY

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** performance, reliability

## Problem

`active_project_ids()` returns project ids in heap order, and that list is serialised straight into the retrieval cache digest, so row order becomes part of every RAG cache key.

## Evidence

- `backend/app/services/retrieval/repository.py:705-715` — `active_project_ids()` is `SELECT p.id::text FROM projects p WHERE p.is_active AND p.knowledge_base_id IS NOT NULL` with no `ORDER BY`.
- `backend/app/graph/tools/knowledge.py:108-110` — the list is fed straight into `_cache_digest(query, project_slug, top_k, project_ids, knowledge_version)`.
- `backend/app/graph/tools/_shared.py:16-18` — `_cache_digest` `json.dumps` the list in order, so row order is part of the key.

## Impact

A heap-order change — any `Project` UPDATE, an autovacuum rewrite, or a plan flip to a parallel/seq scan — silently changes every `rag:knowledge:*` key for the whole deployment at once, producing a mass cache invalidation and a synchronised embed+retrieval stampede (PERF-10). Purely self-inflicted latency and LLM/embed spend.

## Suggested fix

Add `ORDER BY p.id` to `active_project_ids()` and/or sort the digest inputs in Python. One line removes the whole class; no behaviour change is possible.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
