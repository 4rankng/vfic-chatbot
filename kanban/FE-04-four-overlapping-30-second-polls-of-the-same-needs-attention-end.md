---
id: FE-04
title: "Four overlapping 30-second polls of the same needs-attention endpoint per open tab"
severity: high
area: frontend
labels: [performance, reliability]
effort: S
status: todo
found: 2026-09-24
---

# FE-04 — Four overlapping 30-second polls of the same needs-attention endpoint per open tab

**Severity:** high · **Area:** frontend · **Effort:** S · **Labels:** performance, reliability

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

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
