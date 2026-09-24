---
id: FE-12
title: "A 24-hour gcTime with no persister, plus offlineFirst mutations that can replay"
severity: medium
area: frontend
labels: [reliability, performance]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# FE-12 — A 24-hour gcTime with no persister, plus offlineFirst mutations that can replay

**Severity:** medium · **Area:** frontend · **Effort:** S · **Labels:** reliability, performance

**Trạng thái:** TODO

## Problem

Every runtime generation configures `staleTime: 30_000`, `gcTime: 24h` and `networkMode: "offlineFirst"` on both queries and mutations, but no persister is wired up even though two persister packages are declared. With `offlineFirst`, a mutation attempted with no network is held in the mutation cache indefinitely and replayed on reconnect — for a chat product that is a duplicate-send and out-of-order-mode risk.

## Evidence

- `frontend/src/components/atomic-crm/root/reset-runtime-state.ts:41-52` — `staleTime: 30_000`, `gcTime: 1000 * 60 * 60 * 24`, `networkMode: "offlineFirst"` on queries and `networkMode: "offlineFirst"` on mutations.
- `frontend/package.json:48,51` — declares `@tanstack/query-async-storage-persister` and `@tanstack/react-query-persist-client`, but no file in `src` imports them, so the 24 h `gcTime` retains memory in-tab and buys nothing across reloads.
- The replay risk applies to `sendConversationReply`, `markConversationAsRead` and `setConversationMode`. [INFERRED — the offline replay path was not traced end-to-end; the server's `send_unknown` guard may absorb it.]
- Per-feature keys are otherwise disciplined and complete (`["facebook-integration-status"]`, `["facebook-credentials"]`, `["facebook-page-projects", pageId]`, `["knowledge-units", sourceId]`, `["performance-metrics", window]`, `ATTENTION_QUERY_KEY`/`CANDIDATES_QUERY_KEY`), and `dashboard/RecruitingCommandCenter.tsx:104-118` documents a correct intentional `staleTime 25s < refetchInterval 30s` pairing — not a defect.

## Impact

A long-lived tab holds every response ever fetched, and an offlineFirst mutation on a flaky Zalo or recruiter network can be replayed after the user believes it failed.

## Suggested fix

Drop `gcTime` to the 5-minute default unless persistence is actually implemented; either implement the persister (the deps are already declared) or remove both packages. Consider `networkMode: "online"` for chat mutations and keep the server's `send_unknown` as the duplicate guard.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
