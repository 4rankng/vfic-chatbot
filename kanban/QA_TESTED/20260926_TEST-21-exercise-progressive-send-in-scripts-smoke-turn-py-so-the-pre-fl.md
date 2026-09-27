---
id: TEST-21
title: "Exercise progressive_send in scripts/smoke_turn.py so the pre-flip gate covers the streaming path"
severity: medium
area: testing
labels: [testing, release-gate, progressive-send]
effort: M
status: done
column: QA_TESTED

opened: 2026-09-26
---

# TEST-21 — Exercise progressive_send in scripts/smoke_turn.py so the pre-flip gate covers the streaming path

**Severity:** medium · **Area:** testing · **Effort:** M · **Labels:** testing, release-gate, progressive-send

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The blue-green pre-flip smoke gate builds GraphDeps without `progressive_send`, which defaults to False, so the gate exercises only the legacy single-message delivery path. Production serves the progressive two-bubble path (deployed and prod-proven in 684bd3ef), meaning the release gate validates a materially different delivery pipeline than the one candidates receive — a regression in _await_first_bubble/_complete_progressive_prefix (including REL-13's failure-path corruption) sails through the flip. The stub agent also never invokes on_delta, so simply flipping the flag would silently no-op.

## Evidence

- backend/scripts/smoke_turn.py:103-117 — _build_smoke_deps constructs GraphDeps without `progressive_send`
- backend/app/graph/types.py:150-155 — `progressive_send: bool = False` default on GraphDeps
- backend/app/graph/runner.py:186-199 — _progressive_send_enabled requires the flag plus the durable dispatcher seam before any bubble path opens
- backend/scripts/smoke_turn.py:8-19 — the docstring claims the gate exercises 'the exact regression surface' behind the production outages
- backend/tests/test_graph_runner_turn.py:2999-3077 — runner-level progressive tests cover only happy paths; no runner test drives LLMThrottled or an agent error after the early bubble

## Impact

The newest, riskiest delivery machinery ships to prod gated only by unit tests with fakes; the one end-to-end pre-flip check that runs against the real ConversationService cannot see it.

## Suggested fix

Add a streaming variant to smoke_turn.py: a stub agent that feeds text through on_delta, `progressive_send=True`, plus assertions that the early bubble and remainder persist with correct terminal message/outbox states (mirroring _assert_persisted_delivery_invariant); optionally add the runner-level failure-after-bubble tests from REL-13.

## Notes

Pairs with REL-13 — the gate extension is what would have caught it.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
