---
id: FE-11
title: "Two virtualization libraries, and manualChunks still splits the legacy one"
severity: medium
area: frontend
labels: [performance, tech-debt]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# FE-11 — Two virtualization libraries, and manualChunks still splits the legacy one

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** performance, tech-debt

**Trạng thái:** QA_TESTED

## Problem

`manualChunks` gives `/react-virtuoso/` its own vendor chunk, but the inbox thread uses `virtua` and react-virtuoso survives in exactly one place, so the config spends a manual split on the legacy library while the library actually on the hot path has no chunk rule. `zod` also reaches the eager graph with no chunk rule.

## Evidence

- `frontend/vite.config.ts:119-120` — `manualChunks` maps `/react-virtuoso/` to `virtuoso-vendor`.
- `frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:14` — the inbox thread uses `virtua` (`VList`), which is absent from `manualChunks` and therefore lands in whichever chunk imports it (the `conversations` resource chunk).
- `frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.tsx:5` — `GroupedVirtuoso` from react-virtuoso is the single remaining usage of the legacy library.
- `zod` reaches the eager graph via `InstallationBootstrap → root/runtime-manifest.ts:13-18 → runtime-manifest-policy.ts:1` and has no chunk rule.
- Correct and deliberate elsewhere, so do not disturb it: `misc/Markdown.tsx:15-18` dynamic-imports `marked` + `dompurify`, and every resource entry is `lazy()` (`conversations/index.tsx`, `personas/index.tsx`, `projects/index.tsx`, `knowledge*/index.tsx`, `users/index.tsx`, `automation/index.tsx`, `integrations/index.tsx:4-8`).

## Impact

Two virtualization libraries are maintained for one list each (~30–50 KB combined), and the stale chunk rule means the split config no longer describes reality, so future bundle analysis will mislead.

## Suggested fix

Pick one list virtualizer — `virtua` is already the hot path, so migrate `RecruitingCommandCenter` and drop `react-virtuoso` — and update `manualChunks` in `frontend/vite.config.ts` to name `virtua` and `zod`, with a comment that the rule set must track imports.

## Evidence log

- 21221d2c — the last `GroupedVirtuoso` migrated to `virtua` (desktop `VList`, mobile `WindowVirtualizer` since the workspace frame is not a scroll container at ≤767px), with the day grouping flattened into one virtualized child list so headings stay virtualized with their rows.
- `manualChunks` now names `virtua` and `zod` instead of the legacy library. Verified in the build output: `virtua-vendor` and `zod-vendor` exist, `virtuoso-vendor` is gone, and react-virtuoso appears in no chunk.
- `react-virtuoso` removed from `package.json` in 3ca1ee78 once nothing imported it.
- Verified: the render test now exercises the real virtualizer instead of mocking react-virtuoso, and asserts the day-group heading still renders.
- QA 2026-09-24 (orchestrator, first-hand): unit lane 2299 passed + ruff clean; integration lane 130 passed on a disposable Postgres 16 at alembic head; frontend tsc, eslint and vitest 593 all green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
