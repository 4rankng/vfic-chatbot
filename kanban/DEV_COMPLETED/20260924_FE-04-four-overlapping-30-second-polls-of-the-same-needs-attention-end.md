---
id: FE-04
title: "Four overlapping 30-second polls of the same needs-attention endpoint per open tab"
severity: high
area: frontend
labels: [performance, reliability]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# FE-04 — Four overlapping 30-second polls of the same needs-attention endpoint per open tab

**Severity:** high · **Area:** frontend · **Effort:** S · **Labels:** performance, reliability

**Trạng thái:** DEV_COMPLETED

## Problem

Four queries poll the same `/conversations/needs-attention` endpoint every 30 seconds while the inbox is open: one unscoped count, three provider-scoped ones mounted inside the list panel, and a fourth gated on the popover. The query-key namespace is overloaded — element 2 is a provider string in one caller and the literal `"rows"` in another — and no caller invalidates, so each re-polls blindly.

## Evidence

- `frontend/src/components/atomic-crm/layout/topbar/useNotifications.ts:16-24` — `queryKey: ["conversations-needs-attention"]` with `refetchInterval: 1000 * 30`.
- `frontend/src/components/atomic-crm/conversations/ChannelAdapterSelector.tsx:39-47` — three provider-scoped polls on `["conversations-needs-attention", provider]`, each at 30 s, mounted inside the inbox list panel (`conversations/presentation/ConversationList.tsx:498`).
- `frontend/src/components/atomic-crm/layout/topbar/useNeedsAttention.ts:27-36` — a fourth poll on `["conversations-needs-attention", "rows"]`, gated on the popover being open.
- The key collision is real, not dead code: `useNeedsAttention.ts:28` vs `ChannelAdapterSelector.tsx:40` disagree on element 2 of the same namespace.
- `frontend/src/components/atomic-crm/layout/topbar/useNotifications.test.ts:16-20` — the 30 s contract is pinned by a test, so this is intentional rather than accidental; it was simply never consolidated.

## Impact

4 requests per 30 s per open tab against a counting query, with the provider-scoped ones running for providers the user is not viewing — multiplied by every concurrent recruiter on a 2 vCPU / 4 GB droplet.

## Suggested fix

Consolidate into one `useAttentionCounts()` returning `{total, byProvider}` from a single query — the backend already supports `channel_provider`, so one unfiltered call plus client-side bucketing replaces three — raise the interval to 60 s, or drive it from the socket's `message.created` event since the socket is already connected on this screen. Update `useNotifications.test.ts` to the new contract.

## Evidence log

- 1535255c — four pollers collapsed into one `useAttentionCounts()` returning `{total, byProvider}` under a single key family; inbox polling drops from 8 requests/min to 4 and the cadence moves to 60s.
- Per-provider fetches were kept deliberately: the backend returns only `{"count": n}` per provider filter and has no breakdown endpoint, and `contact_channel_identities.provider` is an unconstrained string column, so a derived total could undercount the bell.
- Socket-driven invalidation was evaluated and rejected: `message.created` is routed only to the `conv:<id>` room a client joins by opening that conversation.
- Verified: topbar + `ChannelAdapterSelector` tests pass (8 tests) under the new contract.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
