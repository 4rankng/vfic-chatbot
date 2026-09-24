---
id: REL-06
title: "Outbox PENDING row is dispatcher-visible during the inline send, recording a false ERROR turn"
severity: medium
area: reliability
labels: [reliability]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# REL-06 — Outbox PENDING row is dispatcher-visible during the inline send, recording a false ERROR turn

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** reliability

**Trạng thái:** DEV_COMPLETED

## Problem

`claim_send` inserts the outbox row as PENDING and only then sends inline, while the 60 s dispatcher tick selects *all* PENDING rows with no age gate — so the sweep can win the claim and the turn records an ERROR for a message that was delivered.

## Evidence

- `backend/app/services/conversation/bot_path.py:548-573` — `claim_send` flips the message to SENDING and calls `create_pending_outbox` (row written PENDING) in one transaction.
- `backend/app/services/outbox_service.py:710-720` — `pending_outbox_ids()` selects all PENDING rows with no minimum age.
- `backend/app/services/outbox_service.py:197-226` — `claim_pending_outbox` is atomic, so **exactly one sender wins and there is no duplicate provider POST**. Verified: do not "fix" this.
- `backend/app/services/conversation/bot_path.py:684-698` keeps the message SENT via forward-only rank, but `:628-636` still records `BotRunOutcome.ERROR` when `external_error` is set.

## Impact

The candidate receives exactly one copy, but the dashboard error tile, the `bot_run` audit row and the worker log all record a failure — so a later real-failure investigation starts from false evidence.

## Suggested fix

Insert the outbox row already in SENDING inside the claim transaction (the stale-SENDING path terminalizes at-most-once, so this is safe), or add a minimum-age / `dispatch_claimed_at` gate to `pending_outbox_ids()`.

## Evidence log

- 7e4255b4 — claim_send writes its outbox command already SENDING; dispatch_message_outbox resumes only its own claim
- tests/test_outbox.py, tests/test_concurrency.py; integration/test_inline_claim_outbox_visibility.py

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
