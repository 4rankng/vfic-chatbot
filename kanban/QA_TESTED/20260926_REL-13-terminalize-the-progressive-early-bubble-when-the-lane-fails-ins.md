---
id: REL-13
title: "Terminalize the progressive early bubble when the lane fails instead of overwriting it with reply=''"
severity: high
area: reliability
labels: [reliability, progressive-send, state-machine]
effort: M
status: done
column: QA_TESTED
opened: 2026-09-26
---

# REL-13 — Terminalize the progressive early bubble when the lane fails instead of overwriting it with reply=''

**Severity:** high · **Area:** reliability · **Effort:** M · **Labels:** reliability, progressive-send, state-machine

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

When progressive send claims and dispatches the first bubble mid-generation, the bubble's message row is flipped SENDING with the real text stamped into `body` and its outbox command written already-SENDING. Only the success path (_complete_progressive_prefix) terminalizes that pair. If the lane then fails — agent exception, LLMThrottled after all providers die mid-stream, or the RQ 60 s job timeout — every failure terminal records the turn as 'nothing was sent' against the SAME pending_message_id: record_bot_outcome matches the SENDING row and overwrites `body` with "", and the delivery-rank tie lets the new status win. The candidate keeps a cut-off answer while the audit row lies.

## Evidence

- backend/app/graph/runner.py:1186-1220 — _await_first_bubble claims with `pending_message_id=state.pending_message_id` and dispatches the bubble; only _complete_progressive_prefix later finalizes it
- backend/app/graph/runner.py:905-928 — _record_silent_terminal records reply="" ('nothing was sent') with the same `pending_message_id` on agent error
- backend/app/graph/runner.py:1055-1067 — LLMThrottled is re-raised for the worker; backend/app/workers/chatbot_worker.py:589-621 then records reply="" against the same pending_message_id
- backend/app/services/conversation/send_claim.py:115,:152-163 — claim_send stamps `body = :reply` (the bubble text), sets SENDING, and writes the outbox command already SENDING
- backend/app/services/conversation/bot_outcome.py:120-135,:186-196 — the match set includes SENDING, and `pending_msg.body = reply` plus the delivery-rank tie (app/conversation_messaging/domain/delivery.py:19-29: SENDING=SUPPRESSED=PENDING=0) let the failure status and empty body win
- backend/app/workers/chatbot_worker.py:430-478 — _record_abandoned_turn writes `delivery_status=PENDING` with reply=""; repository.py:614 shows PENDING/SENDING/FAILED BOT rows are the sweep's re-enqueue candidates

## Impact

On the prod-enabled progressive path (deployed with prod proof in 684bd3ef), any mid-stream provider death or 60 s overrun leaves the candidate with a truncated answer, the console showing an empty suppressed message, a SEND_UNKNOWN outbox row, and — in the timeout variant — a likely duplicate answer once the sweep re-enqueues. Dashboards undercount sent replies and cannot correlate the delivered bubble with the turn.

## Suggested fix

Record the delivered bubble on BotRunState when _await_first_bubble claims it; in _record_silent_terminal, the worker's LLMThrottled handler, and _record_abandoned_turn, first finalize_outbound_dispatch the early outbox row, then record the outcome with the bubble text as reply and sent=send_result.ok, so record_bot_outcome stops blanking a delivered row.

## Notes

Pairs with TEST-21 (smoke gate would have caught it). The bubble claim touches the shared AsyncSession while the lane streams; lane DB work completes before streaming starts, so no corruption was observed — fragile sequencing worth knowing when editing.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
