---
id: FE-11
title: "Two virtualization libraries, and manualChunks still splits the legacy one"
severity: medium
area: frontend
labels: [performance, tech-debt]
effort: M
status: todo
found: 2026-09-24
---

# FE-11 — Two virtualization libraries, and manualChunks still splits the legacy one

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** performance, tech-debt

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

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
