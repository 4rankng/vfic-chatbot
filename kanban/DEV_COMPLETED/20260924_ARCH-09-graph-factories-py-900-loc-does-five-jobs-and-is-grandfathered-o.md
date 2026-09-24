---
id: ARCH-09
title: "`graph/factories.py` (900 LOC) does five jobs and is grandfathered out of the import guard"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# ARCH-09 — `graph/factories.py` (900 LOC) does five jobs and is grandfathered out of the import guard

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** IN_PROGRESS

## Problem

The composition root holds port adapters, LLM builders, a process-wide client cache with async retirement, Page-scope resolution and `build_deps` plus six shims. The import guard exempts the file by name, so none of it is checked, although only the client cache actually needs the `app.models`/`app.services` imports.

## Evidence

- `backend/app/graph/factories.py:103,228,306` — `_DirectContextAdapter`, `_FaqBypassAdapter`, `_RuntimePolicyAdapter`; `:346,360,389,444` — LLM builders.
- `backend/app/graph/factories.py:561,577,610,627,708,717` — `_CachedClients`, `_close_client_bundles`, `_schedule_client_retirement`, `_build_cached_clients`, `reset_client_cache`, `aclose_client_cache`.
- `backend/app/graph/factories.py:732-757` — Page-scope resolution; `:760-870` — `build_deps`; `:872-900` — six `_build_*` shims.
- `backend/tests/test_graph_import_guard.py:35` — exempts `factories.py` by name; `backend/app/graph/factories.py:118-120,744-745` — the `app.models`/`app.services` imports that only concern 3 genuinely needs.

## Impact

The guard's exemption is as wide as the file, so the graph's composition root is the one place where graph↔services edges go unchecked; it is also the least testable part of the graph.

## Suggested fix

Extract concern 3 into `graph/client_cache.py` (self-contained, and it already has `reset_client_cache` as its seam) and concern 1 into `graph/adapters.py`. Then narrow the exemption at `backend/tests/test_graph_import_guard.py:35` from "all of factories.py" to the one module that genuinely needs it, which materially strengthens the guard.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
