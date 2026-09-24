---
id: FE-06
title: "Confirmed-dead i18n catalog blocks and four self-testing kit/ components"
severity: medium
area: frontend
labels: [tech-debt, documentation]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# FE-06 — Confirmed-dead i18n catalog blocks and four self-testing kit/ components

**Severity:** medium · **Area:** frontend · **Effort:** S · **Labels:** tech-debt, documentation

**Trạng thái:** QA_TESTED

## Problem

`vietnameseCrmMessages.ts` still ships `resources.{companies,deals,notes,tasks,tags}`, `crm.settings.*`, a large `crm.dashboard.*` block and `crm.image_editor`/`crm.header`/`crm.profile.*`, and per-key greps find no reference outside the catalog file. Separately, `kit/StatCard`, `kit/DataTableCard`, `kit/AlternateCard` and `kit/KitSidebar` have no consumers outside their own test files — one test even asserts `AlternateCard` must not be used — so ~1,000 LOC of components and tests exist only to test themselves.

## Evidence

- `frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:79-175` — `resources.companies` `:79`, `.deals` `:83`, `.notes` `:87`, `.tasks` `:91`, `.tags` `:95`, `crm.settings.companies/deals/notes/tasks` `:154-175`.
- `frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:120-136` (`crm.dashboard.*`), `:188-193` (`crm.image_editor`), `:137` (`crm.header`), `:195` (`crm.profile.inbound/mcp`) — no reference outside the catalog.
- `frontend/src/components/atomic-crm/kit/index.ts:11-23` — exports `StatCard`, `AlternateCard`, `KitSidebar` and `DataTableCard`, all with no consumer outside their own tests.
- `frontend/src/components/atomic-crm/users/account-layout-regressions.test.ts:11-16` — the test actively asserts `AlternateCard` is *not* used, so a regression test is the only thing keeping the component alive.
- Live and must be kept: `kit/PageShell`/`PageHeading`/`EmptyState` (`automation/BotRunList.tsx:6`, `knowledge-base/*`, `users/*`), `misc/LoadingState` (`conversations/presentation/ChatThread.tsx:38`) and `misc/Markdown` (`knowledge/StoredKnowledgePanel.tsx:15`).

## Impact

~100 LOC of unreachable translation keys and ~1,000 LOC of unused-but-tested components inflate the review surface and train readers to think the design system has consumers it does not.

## Suggested fix

Delete the unreferenced `crm.*`/`resources.*` blocks from `vietnameseCrmMessages.ts`, and delete `kit/{stat-card,data-table-card,sidebar}.tsx` plus the `AlternateCard` export and their four test files — or wire them into the pages that currently hand-roll the same chrome. Update whatever doc lists contacts/cases/workflows as dormant.

## Notes

The `contacts/`, `cases/`, `workflows/`, `deals/`, `companies/`, `notes/` and `tasks/` features are **already deleted** — there are no such directories, `capabilities/kernel/index.tsx:165-230` registers exactly 8 resources and `capabilities/static-recruitment-runtime.ts:19-28` is the authoritative id list. The doc that lists them as dormant is wrong today; fix the doc, do not open a deletion ticket. `admin/*-guesser.tsx` (`edit/list/show`) is suspect RA scaffolding, not confirmed dead — grep its consumers first. `automation/` is live (registered as `kernel.resource.bot-runs` at `capabilities/kernel/index.tsx:172-179`).

## Evidence log

- 5751a766 — deleted `kit/{stat-card,data-table-card,sidebar}.tsx`, the `AlternateCard` export and their four test files; kept `PageShell`/`PageHeading`/`EmptyState` and the `tailkit-system.css` token bridge.
- Removed 12 unreferenced catalog blocks from `vietnameseCrmMessages.ts`; every deleted key grep-verified to have zero references, all eight live resources kept.
- Removed the three dangling `registry.json` entries so no manifest path points at a deleted file.
- Verified: kit/users/commons suites 7 files / 23 tests pass.
- QA 2026-09-24 (orchestrator, first-hand): unit lane 2299 passed + ruff clean; integration lane 130 passed on a disposable Postgres 16 at alembic head; frontend tsc, eslint and vitest 593 all green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
