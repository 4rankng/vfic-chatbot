---
id: FE-09
title: "ExternalSourceList hand-rolls a 466-poll, 3h40m polling state machine"
severity: medium
area: frontend
labels: [performance, reliability]
effort: M
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# FE-09 — ExternalSourceList hand-rolls a 466-poll, 3h40m polling state machine

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** performance, reliability

**Trạng thái:** DEV_COMPLETED

## Problem

`ExternalSourceList` derives a 13,200,000 ms (3h40m) sync budget and turns it into 466 follow-up polls, then implements them with 11 `useRef` plus 4 `useState`: a generation guard, an abort controller, a `PollSession` with per-row baseline signatures, a `loadRef` trampoline, a refresh-signal replay guard and a cooldown timer. There is no `document.visibilityState` gate anywhere, so polling continues in background tabs.

## Evidence

- `frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:27-36` — `SINGLE_PAGE_SYNC_MAX_POLL_MS` = 4×30 min + 3×(2000 s) = 13,200,000 ms and `MAX_FOLLOW_UP_POLLS` = 30 + ceil((13.2M − 120k)/30k) = 466.
- `frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:231-235` — the first 30 polls run at 4 s, then 30 s each, and the session stops only when `attempts >= MAX_FOLLOW_UP_POLLS`.
- `frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:182-197` — 11 `useRef` + 4 `useState` implementing the generation guard, abort controller, per-row baseline signatures, `loadRef` trampoline (`:246`, assigned `:296`), refresh-signal replay guard (`:194`, `:325-343`) and cooldown timer (`:355-359`).
- No `document.visibilityState` check exists in the file, so the loop runs regardless of whether anyone is looking at the page.

## Impact

A single open project page issues up to 466 list requests over ~3.7 h, each rendering a full `useState` row array — the most server-hostile frontend loop in the repo against a 2 vCPU box, wrapped in a 466-iteration state machine that is effectively unreviewable.

## Suggested fix

Replace with `useQuery({queryKey: ["external-sources", projectId, variant], refetchInterval: (q) => nextPollDelay(q.state.data)})` — TanStack already pauses on `refetchIntervalInBackground: false` and exposes `isFetching`. Keep the pure helpers as `projects/domain/externalSourceRow.ts` (`rowProgressSignature` `:129`, `statusDotClass` `:68`, `formatTimestamp` `:86`, `truncate` `:126`) and move the table to `presentation/ExternalSourceRow.tsx`, leaving a ~120-LOC component.

## Evidence log

- Landed in 7f28d2a8 (swept in by a directory pathspec alongside FE-07 and FE-12 — attribution recorded here).
- `ExternalSourceList.tsx` 568 → 286 lines: the 466-poll state machine is now `useQuery({refetchInterval: (q) => nextPollDelay(q.state.data, watch, Date.now())})` with `refetchIntervalInBackground: false`; 15 state holders → 7.
- The follow-up policy moved to `projects/domain/externalSourcePolling.ts` (pure, with 5 boundary tests) and row rendering to `projects/presentation/ExternalSourceRow.tsx`.
- Verified: `externalSourcePolling.test.ts` covers the 4s/30s boundary and budget expiry; a new test proves a hidden tab stops polling and resumes.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
