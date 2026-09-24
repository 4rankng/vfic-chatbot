---
id: PERF-10
title: "Single-flight coalescing can never engage, so the retrieval stampede is unmitigated"
severity: medium
area: performance
labels: [performance, reliability]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# PERF-10 — Single-flight coalescing can never engage, so the retrieval stampede is unmitigated

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** performance, reliability

**Trạng thái:** DEV_COMPLETED

## Problem

The single-flight gate requires `project_ids is None`, but `project_ids` is set on every Zalo turn and every Page-scoped turn, so coalescing is off in production. The feature flag and the semantic cache are both off as well.

## Evidence

- `backend/app/graph/tools/knowledge.py:149` — `coalesce_enabled = getattr(s, "singleflight_enabled", False) and project_ids is None`.
- `backend/app/graph/tools/knowledge.py:100-106` — `project_ids` is populated from `active_project_ids()` on every Zalo turn and on every Page-scoped turn, so the condition is false in production.
- `backend/app/core/config.py:273` — `singleflight_enabled` defaults to `False`; `backend/app/core/config.py:201` — the semantic cache is off.
- `backend/app/graph/tools/knowledge.py:197-200` — the single-flight key is already the full cache key (query + project scope + knowledge version), so scoped lookups are safe to coalesce.

## Impact

With 3 `worker-chatbot` replicas, one popular uncached question hit simultaneously is 3 embeds + 3 vector and lexical retrievals + 3 LLM judgements on a 2 vCPU box, and a KB version bump (`bump_kb_caches`) invalidates everything at once — the exact thundering herd the module was built for.

## Suggested fix

Drop the `project_ids is None` gate: the single-flight key already includes the project scope and knowledge version, so scoped lookups are safe to coalesce. Enable `singleflight_enabled` after a gold-set check and keep the existing `await_result` timeout at ≤ the turn budget; the gate removal itself is orthogonal and safe to ship with the flag still off.

## Notes

Perf finding 15 (semantic-cache O(capacity × dim) scan on the event loop and its Page-scope key hole) is covered by **REL-07**; not duplicated here. Both findings are gated by the same `semantic_cache_enabled=False` flag at `backend/app/core/config.py:201`.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
