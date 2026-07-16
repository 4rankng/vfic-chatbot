---
date: 2026-07-16
session: inbox-attention-badge
---

# Journal: 2026-07-16 — Inbox attention badge

## Context

The `Tin nhắn (1)` badge could remain visible after the recruiter had replied,
and selecting it opened the general inbox instead of the conversation that
needed action. The cause was a continuously mounted React Query query with only
`staleTime: 30s`: it becomes eligible to refetch after 30 seconds, but does not
schedule a refetch on its own.

## Change

- Added a 30-second `refetchInterval` to the server-owned
  `/api/v1/conversations/needs-attention` count, keeping navigation state fresh
  while the workspace stays mounted.
- A non-zero Messages badge now links to
  `/conversations?needs_attention=true`. The inbox translates that parameter
  into its existing authoritative server filter, shows the attention chip as
  active, and clears the URL filter through the existing reset path.
- Human and semi-auto rows retain their unread-message count; bot rows suppress
  that count and instead state `Bot chưa phản hồi` when the latest inbound
  message has no later outbound reply.
- Kept zero-count navigation at the normal `/conversations` destination.

## Verification and scope

Verified with 383 frontend app tests, TypeScript typecheck, lint, and the
production build. The change is frontend-only: no backend endpoint, API shape,
database schema, or authorization rule changed. The new deep link reuses the
existing `needs_attention` list contract rather than reproducing attention
logic in the client.
