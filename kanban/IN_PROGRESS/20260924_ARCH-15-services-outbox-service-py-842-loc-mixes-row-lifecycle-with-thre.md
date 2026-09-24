---
id: ARCH-15
title: "`services/outbox_service.py` (842 LOC) mixes row lifecycle with three provider dispatch branches"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: in_progress
column: TODO
opened: 2026-09-24
---

# ARCH-15 — `services/outbox_service.py` (842 LOC) mixes row lifecycle with three provider dispatch branches

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

One module holds the dispatch value objects, the OA token refresh that happens during dispatch, the row lifecycle, the authority revalidation and three provider branches. The dispatcher is the only part that talks to providers.

## Evidence

- `backend/app/services/outbox_service.py:46,56,77,106` — `DispatchCandidate`, `DispatchResult`, `outbound_dispatch_stale_after_seconds`, `build_outbox_payload`; `:86` — OA token refresh during dispatch.
- `backend/app/services/outbox_service.py:135,186,218,596,606,619,642` — `create_pending_outbox`, `claim_pending_outbox`, `dispatch_outbox`, `dispatch_message_outbox`, `pending_outbox_ids`, `stale_sending_outbox_ids`, `claim_stale_sending_unknown`.
- `backend/app/services/outbox_service.py:354,439,578` — `_try_neutral_dispatch`, `_dispatch_facebook`, `_provider_for_outbox_channel`; `:548` — the Messenger send-window policy guard; `:238-305` — authority revalidation.

## Impact

The provider-dispatch surface and the row lifecycle share a module and a review surface, so a lifecycle change (REL-06 touches `claim_pending_outbox`) is reviewed against three provider branches.

## Suggested fix

Natural seam: `outbox/repository.py` (`:135-217`, `:596-657`) versus `outbox/dispatcher.py` (`:218-595`). The dispatcher is the only part that talks to providers.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
