---
title: "Delivery retry containment and worker outcome regression"
date: "2026-07-12"
status: completed
scope: "Backend delivery recovery and chatbot worker reliability"
---

# Delivery retry containment and worker outcome regression

Production evidence showed permanent Zalo OA recipient failures being selected
for reconciliation, causing expensive bot turns to repeat without a possible
delivery. The same investigation exposed a worker-finalization failure: the
conversation-service facade had drifted from the graph and worker callers,
which pass delivery outcome fields through `record_bot_outcome()`.

## Changes

- Restored the facade contract and unchanged delegation for `delivery_status`,
  `trace_id`, and `outcome_metadata`. Signature and forwarding tests now pin
  this boundary so caller/service drift fails in CI instead of during turn
  finalization.
- Made trace-context cleanup conditional on successful initialization. A setup
  interruption can no longer attempt to reset an unset token or leak trace
  context into a later job handled by the same worker process.
- Narrowed reconciliation before lock acquisition: only failed OA deliveries
  whose error contains `user_id is invalid` are excluded as confirmed permanent
  recipient failures. Bot `Not Found` remains retryable because its text is
  not yet a trustworthy structured provider classification. Other failed sends
  remain eligible.
- Removed terminal `SEND_UNKNOWN` messages from candidate selection. They are
  intentionally non-retryable because a transport failure may have delivered
  the message already.

## Verification

- Focused backend checks: 20 passed; final policy-focused rerun: 10 passed.
- Adjacent webhook, graph, and Zalo tests: 86 passed.
- Full backend suite: 701 passed, 18 skipped. Two collection failures were
  environment-only missing optional document/spreadsheet packages.
- Ruff passed for touched backend files. Repository-wide Ruff still reports
  five pre-existing unused-import findings outside this change.

No migration, API contract, configuration, or candidate-facing bot behavior
was changed. The rollback is code-only: reverting these changes restores the
previous reconciliation behavior.
