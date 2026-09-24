---
id: FE-03
title: "The message store never evicts a conversation and three exported selectors are dead duplicates"
severity: high
area: frontend
labels: [performance, tech-debt]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# FE-03 — The message store never evicts a conversation and three exported selectors are dead duplicates

**Severity:** high · **Area:** frontend · **Effort:** S · **Labels:** performance, tech-debt

**Trạng thái:** TODO

## Problem

The Zustand message store holds a `Map` of every conversation ever opened and nothing ever evicts an entry: `clear(convId)` exists but has zero callers repo-wide, `resetAll()` only fires on an `authority_generation` change, and the realtime hook deliberately skips the reset when a warm cache exists. Three exported selectors are also dead duplicates of a `useSyncExternalStore` twin, and the port subscribes unselected so every `set()` notifies all subscribers.

## Evidence

- `frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:37-193` — a Zustand store keyed by `convId` with no eviction bound.
- `frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:182-190` — `clear(convId)` has zero callers; a grep for `.clear(`/`resetAll(` across `conversations/**` finds exactly one caller, `conversations/reset-runtime.ts:17 → resetAll()`.
- `frontend/src/components/atomic-crm/conversations/presentation/use-conversation-realtime.ts:80-86` — switching conversations deliberately skips the reset when a warm cache exists (`if (!existing || existing.byId.size === 0) resetMessages(...)`).
- `frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:204-258` — `useConversationMessages` `:204`, `useConversationFlags` `:214` and `getNewestRealMessageId` `:246` have no importers; the live equivalents are re-implemented on `useSyncExternalStore` in `conversations/presentation/conversation-message-state.ts:1-82`.
- `frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:197` — the port uses the unselected `subscribe`, so every `set()` notifies all subscribers.

## Impact

A recruiter who opens 500 conversations in a shift holds ~10k message objects plus per-conversation Maps for the tab's lifetime — combined with `gcTime: 24h` in `root/reset-runtime-state.ts` a long-lived tab never returns memory. Two copies of the selector logic also mean a `sortedCache` fix can be applied to the wrong one.

## Suggested fix

Call `clear(convId)` when the active conversation changes past a small LRU bound (keep the last ~5), or drop the cache-persistence feature and reset on switch. Delete `message-store.ts:200-258` and `getNewestRealMessageId`, keeping `useMessageStore` + `conversationMessageStatePort`, and move selection into the store or use `subscribeWithSelector` to cut notification fan-out.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
