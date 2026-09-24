---
id: ARCH-18
title: "Import-time registry validation with failure semantics, and dormant `models/case.py` tables to record rather than drop"
severity: low
area: architecture
labels: [tech-debt]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# ARCH-18 — Import-time registry validation with failure semantics, and dormant `models/case.py` tables to record rather than drop

**Severity:** low · **Area:** architecture · **Effort:** S · **Labels:** tech-debt

**Trạng thái:** QA_TESTED

## Problem

`capabilities/registry.py` runs its dependency-graph and owner validation during import, so a pack defect becomes an import-order-dependent startup crash rather than a startup check. Separately, the `case.py` tables have no runtime reader or writer but sit behind a load-bearing foreign key, so they cannot be dropped casually.

## Evidence

- `backend/app/capabilities/registry.py:196` — `_REGISTRY = CapabilityRegistry(...)` runs `_validate_dependency_graph` (`:148`) and `_validate_owners` (`:172`) at import, so any pack defect raises `ValueError` while importing `app.capabilities`.
- `backend/app/graph/prompts.py:11-13` — the persona read at import is documented as intentional fail-fast, so it is deliberate, not debt.
- `backend/app/models/__init__.py:1-8` — imports all 23 model modules, so importing `app.models.base` (which `backend/app/core/db.py:11` does) does not itself register the full `Base.metadata`; `backend/app/models/conversation.py:25-26` adds two more edges to the model import graph.
- `backend/app/models/case.py` — `Case`, `CaseNote`, `CaseFollowup`, `CaseTagAssignment`; `backend/app/models/case_workflow.py` — `CaseWorkflowTransition`, `CaseTagDefinition`; grep across `backend/` returns only `backend/app/models/__init__.py:32-45,131-136` and docstrings.
- `backend/app/services/installation/service.py:118,306,816` and `backend/app/models/installation.py:51-56` — `CaseWorkflowVersion` is validated and FK-targeted, so the surrounding case tables cannot be dropped in a routine cleanup.

## Impact

An import-order-dependent startup crash instead of a startup check, and a future reader who rediscovers the dormant case tables may drop a table that a live FK depends on.

## Suggested fix

Move the registry validation into an explicit `verify_registry()` called from app startup (or a single test), keeping `_REGISTRY` construction as pure data. For `models/case.py`, do not drop the tables in this pass — Alembic is an approval gate per `AGENTS.md` — instead mark the dormant models with an explicit comment naming them as unmapped-in-practice and add a single test asserting they have no importer, so the dormancy is recorded rather than rediscovered.

## Notes

Merged ticket: covers audit findings F19 and F20 (both low).

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
