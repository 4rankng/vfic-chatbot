---
id: REL-01
title: "A partially delivered multi-bubble answer is recorded FAILED, so recovery answers again"
severity: high
area: reliability
labels: [reliability]
effort: M
status: todo
found: 2026-09-24
---

# REL-01 — A partially delivered multi-bubble answer is recorded FAILED, so recovery answers again

**Severity:** high · **Area:** reliability · **Effort:** M · **Labels:** reliability

## Problem

Answers longer than 420 characters are sent as N separate provider requests. When chunk N fails with a *definite* provider error, the aggregate result is `ok=False` carrying chunk 1's message id and a null error class — which is recorded as `FAILED`, after which the reconcile sweep treats it as a lost turn and re-answers the candidate.

## Evidence

- `backend/app/services/zalo_bot_service.py:96-97` — `ZALO_VISIBLE_BUBBLE_CHARS = 420`, so any answer over 420 chars is multi-request.
- `backend/app/services/zalo_bot_service.py:214-269` (`_aggregate_chunked_send`) — on failure returns `ok=False`, `msg_id=message_ids[0]` (`:251`), `error_class=result.error_class` (`:254`).
- `backend/app/graph/runner.py:1073-1079` — only `AMBIGUOUS_SEND_CLASSES` map to SEND_UNKNOWN, so a definite mid-chunk failure becomes `FAILED` (`backend/app/services/conversation/bot_path.py:610-618`).
- `backend/app/services/conversation/repository.py:459-533` admits a newest BOT message with `delivery_status IN ('PENDING','SENDING','FAILED')`; `backend/app/workers/reconcile_worker.py:211-212` classifies it `failed_send` and re-enqueues after the 900 s backoff (`:49`).

## Impact

On the Zalo Bot channel there are no receipts, so the FAILED row is permanent and the duplicate reply is deterministic — the candidate gets the answer twice, including chunk 1 twice. On the OA channel a `user_received_message` receipt for chunk 1 can rescue the row (`receipt_advances(FAILED, DELIVERED)`), which is why this is intermittent rather than universal. A chunk failing with a *transport* error is correctly routed to SEND_UNKNOWN and is not affected.

## Suggested fix

Make `_aggregate_chunked_send` distinguish partial delivery: when `message_ids` is non-empty, return SEND_UNKNOWN (at-most-once) or a dedicated `partial` outcome — never a bare `ok=False` with a null error class. Persist one `Message` row per bubble (or a `provider_message_ids` list) so partial delivery is representable, and exclude `FAILED` rows with a non-null `zalo_message_id` from the `failed_send` recovery branch.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
