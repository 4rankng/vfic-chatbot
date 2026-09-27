---
id: ARCH-20
title: "Split graph/runner.py: 2153-LOC turn orchestrator mixes 7 responsibilities"
severity: high
area: architecture
labels: [god-module, chat-hot-path]
effort: L
status: done
column: QA_TESTED

opened: 2026-09-26
---

# ARCH-20 — Split graph/runner.py: 2153-LOC turn orchestrator mixes 7 responsibilities

**Severity:** high · **Area:** architecture · **Effort:** L · **Labels:** god-module, chat-hot-path

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

graph/runner.py is a single 2153-line module that owns every stage of a bot turn: progressive streaming/early bubbles, outbox claim+dispatch, lane routing, authority gating, telemetry stamping, typing heartbeat, and the run_turn entrypoint. Any change to any stage edits the same file, and the module is on the chat hot path (imported by workers/chatbot_worker and the webhook flow), making it the highest-conflict file in the churned backend. The stage functions already communicate through narrow parameters, so they split cleanly along existing seams.

## Evidence

- backend/app/graph/runner.py:190 — _ProgressiveStream + _EarlyBubble (:212) + _next_sendable_offset (:139) + _await_first_bubble (:1337) + _complete_progressive_prefix (:1476) implement progressive bubble delivery inline
- backend/app/graph/runner.py:277 — _build_outbox_payload/_dispatch_claimed_message (:292)/_claim_and_dispatch (:1156)/_record_dispatched_outcome (:1240) implement claim+dispatch of the durable outbound command
- backend/app/graph/runner.py:362 — _agent_turn (:362-665), _direct_context_turn (:667), run_manifest_composed_agent (:709), _resolve_lane (:993) and the vacancy/income arg builders (:913-975) implement lane routing
- backend/app/graph/runner.py:824 — _authority_gate plus _record_silent_terminal (:786) implement ownership stand-down and outcome recording
- backend/app/graph/runner.py:754 — _status_heartbeat/_cancel_status_task implement channel typing UX; :322/:329/:894 implement timing/telemetry stamping
- backend/app/graph/runner.py:1590 — run_turn is the 560+ line end-to-end entrypoint tying all of the above together (file total 2153 lines)

## Impact

Every turn-level feature lands in one file reviewers must re-read in full; the seven concerns cannot be unit-scoped without importing the whole orchestrator, and merge conflicts concentrate on the hottest file in the backend.

## Suggested fix

Extract along the existing seams into graph/ modules: progressive.py (_ProgressiveStream, _EarlyBubble, _next_sendable_offset, _await_first_bubble, _complete_progressive_prefix), dispatch.py (_build_outbox_payload, _dispatch_claimed_message, _claim_and_dispatch, _record_dispatched_outcome), lanes.py (_agent_turn, _direct_context_turn, _resolve_lane, route arg builders), authority.py (_authority_gate, _record_silent_terminal), telemetry.py (_stamp_* helpers), keeping run_turn in runner.py as the composition point. No behavior change; tests keep passing against re-exports during the move.

## Notes

REL-13/REL-14 and SEC-9 all edit this file — land the behavior cards or this split first, not both in the same window.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
