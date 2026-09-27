---
id: FE-28
title: "Decompose ChatThread: a CCN-92 component in an 882-line presentation module"
severity: medium
area: frontend
labels: [function-hotspot, conversations]
effort: M
status: done
column: QA_TESTED
opened: 2026-09-27
---

# FE-28 — Decompose ChatThread: a CCN-92 component in an 882-line presentation module

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** function-hotspot, conversations

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

ChatThread.tsx (882 lines, 765 nloc) is the conversation thread's presentation module, and its ChatThread component (:331) alone reaches CCN 92 — the highest cyclomatic complexity of any frontend component in the repowise production scan — while the file churns at the repo p80 for recent commits. Message grouping, bubble variants, status rails, and composer interplay all live in the one body.

## Evidence

- frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx — 882 lines, score 4.25/10 (repowise get_health production scope)
- frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:331 — export const ChatThread: CCN 92, nesting 3
- repowise function-hotspot biomarker: modified across 3 recent commits (repo p80 = 3)

## Impact

The inbox's most-edited surface is also its most complex function; every thread feature pays re-read cost, and regressions concentrate where review attention is thinnest.

## Suggested fix

Extract message-grouping and bubble-variant sub-components beside the module per the FE-13 conversations layout, memoizing on real inputs (the FE-05 view-model pattern). While splitting, route data access through an application-layer port so the file stops importing providers/rest/dataProvider directly — that edge is the recorded QA gate on FE-08.

## Notes

FE-05 and FE-08 both touched this file's neighborhood; land after those are QA-closed to avoid rework.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
