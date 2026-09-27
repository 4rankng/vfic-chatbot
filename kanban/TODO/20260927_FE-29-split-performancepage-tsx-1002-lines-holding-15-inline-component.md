---
id: FE-29
title: "Split PerformancePage.tsx: 1002 lines holding ~15 inline components"
severity: medium
area: frontend
labels: [god-module, reporting]
effort: M
status: todo
column: TODO
opened: 2026-09-27
---

# FE-29 — Split PerformancePage.tsx: 1002 lines holding ~15 inline components

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** god-module, reporting

**Trạng thái:** TODO

## Problem

PerformancePage.tsx is a 1002-line single module (980 nloc, maintainability 4.0) defining the whole performance dashboard inline: Status, Metric, PerformanceLoading, PerformanceError, AttentionQueue, StageMatrix, AdapterComparison, MobileDiagnostics, TurnDetail, MobileTurnCard, SlowestTurns, SupportingStats, and PerformanceNoActivity are all file-local components stacked in one file. It is also a change-entropy hotspot (top 3.4% for scattered churn), so the inline stack keeps absorbing edits.

## Evidence

- frontend/src/components/atomic-crm/performance/PerformancePage.tsx — 1002 lines, 980 nloc, maintainability 4.0, weighted deficit 5,390 (repowise get_health production scope)
- frontend/src/components/atomic-crm/performance/PerformancePage.tsx:52-:796 — thirteen file-local components (Status :52, Metric :69, PerformanceLoading :92, PerformanceError :103, AttentionQueue :137, StageMatrix :242, AdapterComparison :350, MobileDiagnostics :414, TurnDetail :472, MobileTurnCard :515, SlowestTurns :594, SupportingStats :741, PerformanceNoActivity :796)
- frontend/src/components/atomic-crm/reporting/domain/performanceDiagnostics.ts — the domain module this page already reads from, but the page keeps its own inline presentation stack

## Impact

The dashboard's four reporting windows share one file, so any metric tweak is a 1002-line review; the entropy signal says the file keeps attracting edits, which compounds the cost.

## Suggested fix

Move the file-local components into performance/presentation/ grouped by their window (attention queue, stage matrix, adapter comparison, slowest turns, supporting stats), share Status/Metric through a small primitives module, and keep PerformancePage as the composition root. Existing page tests keep their imports via the same module path or updated spec imports.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
