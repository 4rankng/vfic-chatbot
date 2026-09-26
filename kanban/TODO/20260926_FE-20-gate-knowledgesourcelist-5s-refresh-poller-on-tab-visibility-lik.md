---
id: FE-20
title: "Gate KnowledgeSourceList 5s refresh poller on tab visibility like ExternalSourceList"
severity: medium
area: frontend
labels: [frontend, polling, regression-risk]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# FE-20 — Gate KnowledgeSourceList 5s refresh poller on tab visibility like ExternalSourceList

**Severity:** medium · **Area:** frontend · **Effort:** S · **Labels:** frontend, polling, regression-risk

**Trạng thái:** TODO

## Problem

The wave-1 sweep migrated ExternalSourceList's follow-up polling to TanStack Query with refetchIntervalInBackground: false, but its sibling KnowledgeSourceList still runs a raw window.setInterval calling react-admin's useRefresh() every 5 s while any source is mid-pipeline. The effect has teardown but no visibility gating, so a hidden tab keeps issuing refetches for as long as a source stays in the pipeline — and knowledge pipelines are long-running.

## Evidence

- frontend/src/components/atomic-crm/knowledge/KnowledgeSourceList.tsx:131-135 — useEffect creates window.setInterval(() => refresh(), 5000) whenever any source has isPipelineActive; teardown only clears the timer; visibilityState is never consulted (repo-wide grep: only InstallationBootstrap.tsx and ExternalSourceList.test.tsx touch visibility)
- frontend/src/components/atomic-crm/knowledge/KnowledgeSourceList.tsx:152-156 — the header renders 'Đang xử lý, tự làm mới mỗi 5 giây', confirming the cadence runs for the whole pipeline duration
- frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:87-94 — the certified sibling derives refetchInterval from row state and sets refetchIntervalInBackground: false ('a hidden tab must not keep hitting the backend')
- frontend/src/components/atomic-crm/projects/ExternalSourceList.test.tsx:324-332 — the fixed sibling pins hidden-tab behavior in a test; KnowledgeSourceList has no equivalent

## Impact

An operator who leaves a knowledge page open in a background tab keeps the SPA refetching the knowledge_sources list every 5 s for the full pipeline duration (tens of minutes), multiplying avoidable backend load and battery drain; the effect also re-arms on every refetch because sources gets a new array identity each cycle.

## Suggested fix

Gate the effect on document.visibilityState (skip scheduling when hidden, add a visibilitychange listener that resumes/clears the interval), or migrate the source list to TanStack Query with derived refetchInterval + refetchIntervalInBackground: false mirroring externalSourcePolling.ts. Add a hidden-tab regression test alongside ExternalSourceList.test.tsx:295-333.

## Notes

Same class as the ExternalSourceList poller fixed in wave 1 — this is the missed sibling, i.e. a sweep regression risk.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
