---
id: ARCH-25
title: "Split remaining >600-LOC modules: conversation/repository.py, recruiter_path.py, chatbot_worker.py"
severity: medium
area: architecture
labels: [god-module, chat-hot-path]
effort: M
status: done
column: QA_TESTED

opened: 2026-09-26
---

# ARCH-25 — Split remaining >600-LOC modules: conversation/repository.py, recruiter_path.py, chatbot_worker.py

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** god-module, chat-hot-path

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

Three more files crossed the 600-line threshold with mixed responsibilities. ConversationRepository (704) mixes CRM inbox reads with the reconcile-sweep SQL machinery. RecruiterMessagingState (664) stacks takeover lifecycle, recruiter messaging, delivery receipts, and follow/unfollow in one class. workers/chatbot_worker.py (658) stacks the direct-ASGI turn bridge, RQ enqueueing, the crash guard, mid-turn handoff, and timings builders. Each is cohesive enough to split mechanically along its existing sections.

## Evidence

- backend/app/services/conversation/repository.py:149 — ConversationRepository (704 lines): viewer-scoped CRM reads (list :256, needs_attention_count :346) alongside reconcile SQL (find_reconcile_candidates :536, latest_inbound_never_given_a_turn :661)
- backend/app/services/conversation/repository.py:82 — the reconcile SQL block (_MASKED_INBOUND_SQL + find_reconcile_candidates) is ~170 lines of embed-string SQL inside the CRM repository
- backend/app/services/conversation/recruiter_path.py:61 — RecruiterMessagingState (664 lines): takeover/release/semi-auto (:77,:134,:194), close/reopen/clear/delete (:252-347), recruiter messaging (:356-519), receipts (:522-618), follow/unfollow (:638-663)
- backend/app/workers/chatbot_worker.py:26 — direct-ASGI turn scheduling/bridge (:26-150) vs RQ enqueue (:152,:172) vs crash guard (:389,:471) vs handoff (:325) vs timings builders (:275,:300); 658 lines

## Impact

The reconcile sweep, recruiter inbox actions and worker crash recovery are independently changing concerns that share one file each; reviewers of a CRM query tweak must diff past the lost-turn SQL, and worker lifecycle changes sit next to enqueue policy.

## Suggested fix

Low-risk mechanical moves: (1) split conversation/repository.py into repository.py (reads) + reconcile_queries.py (the _MASKED_INBOUND_SQL block, find_reconcile_candidates, latest_inbound_never_given_a_turn — the reuse keeps a single SQL definition); (2) split recruiter_path.py's messaging/receipt half into recruiter_receipts.py; (3) split chatbot_worker.py's direct-ASGI bridge into direct_turn.py and keep enqueue + job entrypoints + crash guard in chatbot_worker.py. Re-export from the old paths so test import sites stay valid, then update callers.

## Notes

recruiter_path.py's docstring shows decomposition is already the accepted pattern (state.py/bot_path.py/recruiter_path.py); this finishes it.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
