---
id: REL-8
title: "Initialize `candidate` before try in run_proactive_turn so the error path records the outcome and releases the lock"
severity: medium
area: reliability
labels: [error-path, workers, proactive-followup]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-26
---

# REL-8 — Initialize `candidate` before try in run_proactive_turn so the error path records the outcome and releases the lock

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** error-path, workers, proactive-followup

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

run_proactive_turn assigns `candidate` only at proactive.py:354 inside the try, but the finalization after the except block unconditionally reads `candidate`. The except deliberately converts any in-try exception into `SendOutcome(ok=False)` so the failure is recorded via record_proactive_outcome — but any exception raised before line 354 (LLM call, build_system_prompt, last_messages, direct_context.resolve) crashes the finalizer with UnboundLocalError instead.

## Evidence

- backend/app/graph/proactive.py:354 — `candidate = strip_think_reasoning(message)` is the FIRST assignment of `candidate`, deep inside the try block
- backend/app/graph/proactive.py:440-442 — `except Exception as exc:` converts any earlier failure into `result = SendOutcome(ok=False, ...)`
- backend/app/graph/proactive.py:446-447 — post-except finalization builds `record_kwargs = {"message": candidate, ...}` unconditionally → UnboundLocalError when the exception fired before :354
- backend/app/graph/proactive.py:457 — `await svc.state.record_proactive_outcome(conv, **record_kwargs)` is therefore never reached on that path
- backend/app/services/conversation/bot_outcome.py:174-193 — the per-chat bot lock is cleared inside record_proactive_outcome, so skipping it leaks the lock
- backend/app/core/config.py:273 — bot_lock_ttl_seconds: int = 180 (the leak is time-bounded)

## Impact

On a transient LLM/provider failure during a proactive nudge, the designed failure record is lost: the 180s per-chat bot lock is held (blocking the reactive bot path and the follow-up scan for that conversation), the flushed last_followup_attempt_at stamp is rolled back at session close, so the conversation stays fully eligible and the next 30-min tick retries and re-crashes — up to the 48h window. Logs show UnboundLocalError instead of the provider error.

## Suggested fix

Initialize `candidate = ""` next to `pending_message_id`/`outbox_channel` so the except-path finalization can always reach record_proactive_outcome, which then clears the lock and durably records the failure. Add a regression test that raises inside a fake deps.agent.agent and asserts the lock columns clear and the outcome is recorded.

## Notes

Same pattern class as REL-04 (already fixed for the email send); this is the sibling gap in the proactive turn finalization.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
