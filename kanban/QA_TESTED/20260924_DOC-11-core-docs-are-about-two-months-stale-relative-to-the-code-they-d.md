---
id: DOC-11
title: "Core docs are about two months stale relative to the code they describe"
severity: medium
area: docs
labels: [documentation]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# DOC-11 — Core docs are about two months stale relative to the code they describe

**Severity:** medium · **Area:** docs · **Effort:** M · **Labels:** documentation

**Trạng thái:** QA_TESTED

## Problem

Five of the six core documents carry July timestamps while roughly 60 commits have landed since mid-September, including the TypeSafe Jev router replacement, gender inference, the context-window resolver and the Facebook Page work. `AGENTS.md` requires doc updates for exactly these change classes, so the drift is a process failure rather than a doc exemption.

## Evidence

- `docs/code-standards.md:3` "Last updated: 2026-07-22", `docs/codebase-summary.md:4` 2026-07-23, `docs/system-architecture.md:3` 2026-07-23, `docs/project-overview-pdr.md:4` 2026-07-24, `docs/deployment-guide.md:3` 2026-07-26; only `docs/project-roadmap.md:3` (2026-09-21) is current.
- `.git/logs/HEAD` shows ~60 commits since 2026-09-14 alone, including the router replacement (`20d3913`, `cfeee38`), gender inference (`59a3c83`, `e9543d4`), the context-window resolver (`a5c4e21`) and the Facebook Page work — none reflected in the five documents above.
- `docs/code-standards.md:139-141` still describes resources as "registered in `components/atomic-crm/root/CRM.tsx` (8 total…)" while `frontend/src/components/atomic-crm/root/CRM.tsx:92-94` renders them from `runtime.resources` supplied by `capabilities/static-recruitment-runtime.ts`.
- `AGENTS.md:63-64` requires doc updates for user-visible behaviour, setup, architecture and contracts — all of which the changes above are.

## Impact

Engineers and agents plan against a July picture of a September codebase, and the wrong resource-registration model in `docs/code-standards.md` is exactly the kind of claim that leads to a confidently wrong edit.

## Suggested fix

Backfill `TECH.md` and `docs/codebase-summary.md` now (with DOC-03), then stop hand-maintaining the fast-drifting facts: add a CI step asserting `docs/codebase-summary.md`'s migration-head string equals `alembic heads` output, and refresh the "Last updated" stamps in the change that touches the behaviour.

## Notes

Merge with DOC-03 — same documents, same regeneration fix.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
