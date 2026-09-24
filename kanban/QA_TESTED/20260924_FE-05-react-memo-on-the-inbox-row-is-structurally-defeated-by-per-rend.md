---
id: FE-05
title: "React.memo on the inbox row is structurally defeated by per-render row allocation"
severity: high
area: frontend
labels: [performance]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# FE-05 — React.memo on the inbox row is structurally defeated by per-render row allocation

**Severity:** high · **Area:** frontend · **Effort:** M · **Labels:** performance

**Trạng thái:** QA_TESTED

## Problem

`ConversationList` builds `rows` by allocating a new object per conversation inside a `useMemo` whose deps include `adapterPresentations`, `snippets`, `deferredQuery` and `readIds`, so every rebuild changes the identity of every `conversation` prop. `ConversationListItem` is `memo(...)` and its comment claims memo protects against exactly the three cases — typing in search, marking another row read, a sibling's realtime update — where `rows` is rebuilt and the shallow compare always fails.

## Evidence

- `frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:448-474` — `rows` allocates `{...c, _presentation, _snippet}` per conversation inside the `useMemo`, whose deps are `[adapterPresentations, conversations, snippets, deferredQuery, readIds]`.
- `frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:137-140` — `ConversationListItem` is `memo(...)`, with the memo rationale asserted in the comment at `:132-136`.
- `frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:438-445` — `snippets` is replaced wholesale on every list fetch via `setSnippets((prev) => ({...prev, ...snips}))`.
- `frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:607` — `pendingReadIds` is a new `Set` on each open and is also passed into the sort comparator at `:473`.
- Avatar and unread styles were carefully hoisted at `:68-115` to avoid allocation, so the remaining per-row allocation is an oversight rather than a design choice.

## Impact

On a 25-row list every deferred keystroke rebuilds 25 objects, re-sorts, and re-renders 25 memo'd components that then fail to skip. This is client-side only, but it is the most-touched screen in the product and low-end Android recruiters are the target.

## Suggested fix

Split the row view-model: keep `rows` as the raw `conversations` array and pass `presentation`/`snippet` as separate props pulled from a per-id `Map<convId, rowVM>` cache memoized on `conversationIdsKey`, so identity is stable while inputs are unchanged. Pass the single `isRead: boolean` for a row instead of the whole `readIds` set, so read state cannot invalidate row identity.

## Evidence log

- ff2fbfc3 — rows keep the raw `conversations` array for identity; `presentation`/`snippet` resolve through a per-id view-model cache (`conversation-row-view-model.ts`) that reuses the previous object while inputs are unchanged. The row takes its own `isRead` boolean instead of the shared `Set`, and `onSelect` is stabilised via a ref.
- Verified by falsifiable render tests: a search keystroke and a read-toggle each leave sibling rows un-rendered, each with a positive control. Both tests fail if the view-model reuse or the stable `onSelect` is reverted.
- QA 2026-09-24 (orchestrator, first-hand): unit lane 2299 passed + ruff clean; integration lane 130 passed on a disposable Postgres 16 at alembic head; frontend tsc, eslint and vitest 593 all green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
