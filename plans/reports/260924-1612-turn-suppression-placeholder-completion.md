# Agent Completion Checklist — stuck-turn suppression + placeholder leak

## Task record

- Task: Fix the production bug where a candidate's message gets no answer while the
  conversation shows a stuck "Đang soạn trả lời..." placeholder (bot_run 773 SUPPRESSED
  with a valid `proposed_reply`).
- Scope: `backend/app/graph/runner.py` (read/verified), `backend/app/services/conversation/bot_path.py`,
  `backend/app/services/conversation/scheduler.py`, `backend/app/workers/chatbot_worker.py`
  (turn body, crash guard, ingress-enqueue path). Explicit non-goal: gender inference
  (already shipped — left untouched).
- Files changed:
  - `backend/app/services/conversation/bot_path.py` — `record_bot_pending` resolves any
    open BOT/PENDING row for the conversation before creating the new one.
  - `backend/app/services/conversation/scheduler.py` — `enqueue_latest_unanswered_worker_message`
    accepts `execution_source` (default `"queued"`, unchanged for existing callers).
  - `backend/app/workers/chatbot_worker.py` — `_handoff_to_newer_inbound` +
    `_inbound_provider_id`; `_record_abandoned_turn` resolves the dead turn's placeholder;
    `_run_job_async_inner` publishes the pending row id and calls the hand-off.
  - Tests: `tests/test_chat_turn_handoff.py` (new), `tests/test_chat_turn_abandonment.py`,
    `tests/test_concurrency.py`, `tests/test_graph_runner_turn.py`, `tests/test_webhooks.py`.
- Instructions retrieved: `AGENTS.md`, `docs/testing.md` (not needed beyond the narrow
  lane), the conversation/bot-path and worker modules, `standards/agent-completion-checklist.md`.
- Approval required: No. No prompt/persona change, no webhook signature/auth change, no
  Alembic revision, no dependency change, no protected path edited.
- Approval evidence: `git status --short` shows only the files above; no `alembic/versions`
  or `app/api/webhooks.py` modification.

## Root cause (evidence)

**Two independent defects compound into "no answer at all".**

1. **The second inbound is dropped while the first turn holds the mutex.**
   `ZaloWebhookService.handle` persists the inbound and then, if `acquire_lock` fails,
   returns `{"status": "locked"}` without enqueuing a job (`app/services/webhook.py:203`;
   the Messenger ingress has the same drop at
   `app/conversation_messaging/infrastructure/webhook_delivery.py:74`). The persisted
   inbound bumps `conversations.version` (`app/services/conversation/bot_path.py:249`), so
   the in-flight turn's atomic claim (version + lock owner + liveness,
   `bot_path.py:506-541`) fails and it is recorded SUPPRESSED — the observed run 773.
   The turn's outcome row is written *after* the dropped message, and the reconcile sweep
   only considers a conversation whose **newest** message is a WORKER row or a
   BOT PENDING/SENDING/FAILED row (`app/services/conversation/repository.py:494`), so the
   SUPPRESSED/SENT row masks the unanswered "Hello" from recovery for good: no BotRun is
   ever recorded for it and the candidate is answered nothing. Both halves confirmed:
   mechanism 1 (version bump + claim gate + sweep predicate), not a send failure.

2. **The placeholder row is not resolved on the paths that die.**
   `record_bot_outcome(..., sent=False, pending_message_id=...)` *does* resolve the row in
   place — verified, see gate 4 below, including claim-failure, agent-error, empty-reply
   and authority-gate suppression (`runner.py:671,739,1041,1086`). The leaks were:
   - a turn killed **after** `record_bot_pending` (`runner.py:1299`) but before its outcome
     (RQ job timeout → `JobTimeoutException`, crash, or any raise in that window):
     `_record_abandoned_turn` inserted a **second** BOT/PENDING row and left the
     "Đang soạn trả lời..." row open;
   - a turn killed with no code path at all (SIGKILL/OOM, worker shutdown) left the row
     open for the next turn; the sweep only resolves it while it is the newest message and
     within `reconcile_max_age_seconds` (24 h, `app/core/config.py:365`) — the observed
     09-22 rows were already outside that window, hence permanent.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | (a) hand-off: `test_chat_turn_handoff.py` (6 tests); (b) placeholder: `test_chat_turn_abandonment.py::test_abandoned_turn_resolves_its_placeholder_row`, `test_concurrency.py::test_record_bot_pending_resolves_a_predecessor_placeholder`, 3 runner silent-terminal tests |
| Diff is limited to the approved scope | PASS | `git diff --stat`: 3 source files (100 insertions), 5 test files; no runner.py edit needed (its four silent paths already resolve the row — pinned by tests) |
| Protected operations were avoided or approved | PASS | No commit/push/branch/deploy; no `alembic/versions`, no `core/{config,security,ratelimit}.py`, no `api/webhooks.py`, no persona/prompt, no manifest |
| Focused tests/checks pass | PASS | `.venv/bin/pytest -m "not integration" -q tests/test_graph_runner_turn.py tests/test_concurrency.py tests/test_chat_turn_abandonment.py tests/test_chat_turn_handoff.py tests/test_llm_semaphore.py tests/test_webhooks.py tests/test_reconcile_worker.py tests/test_reconcile_repository.py tests/test_conversation_release.py tests/test_direct_turns.py tests/test_outbox.py tests/test_record_bot_outcome_contract.py tests/test_turn_deadlines.py` → 259 passed |
| Broader regression tests pass when shared behavior changed | PASS | 567 passed across every `tests/*.py` matching worker/conversation/graph/outbox/webhook/llm/reconcile/direct/turn/pending/chat/smoke/architecture |
| Lint passes for affected code | PASS | `.venv/bin/ruff check .` → All checks passed |
| Type checking passes for affected code | N/A | No type checker configured in the repo (`pyproject.toml` has only `[tool.ruff]` + `[tool.pytest.ini_options]`) |
| Build/import validation passes for affected code | PASS | `.venv/bin/python -c "import app.workers.chatbot_worker, app.services.conversation.bot_path, app.services.conversation.scheduler"` |
| Security and privacy impact reviewed | PASS | No secret/PII added; the hand-off logs only `conversation_id` (never message text), mirroring the existing turn logs; no auth/webhook-signature change |
| Performance and async-I/O impact reviewed | PASS | One extra session + 2 indexed reads (`get`, `latest_worker_message`) per turn, plus one no-op `UPDATE messages` per turn in `record_bot_pending`; no blocking I/O added; the hand-off enqueues on the low-priority `recovery` queue |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change; the candidate-visible effect is that the "Đang soạn trả lời..." bubble no longer sticks |
| Error handling and compatibility reviewed | PASS | Hand-off is wrapped and best-effort; `pending_message_id` in the job dict is additive (legacy payloads read as `None`); `execution_source` has a default so existing callers are unchanged; SUPPRESSED semantics preserved (no blanket convert-to-send) |
| Documentation impact handled | PASS | N/A for docs (internal recovery behavior, no user-visible setup/API change); behavior documented in the changed docstrings |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff` contains none |
| Final `git diff --check` passes | PASS | `git diff --check` → OK |
| Final `git status --short` reviewed | PASS | Only the 8 files listed above |

## Result

- Overall status: PASS for the assigned scope (implementation + tests); deployment is the
  parent's step.
- Remaining risks or follow-ups:
  1. **Hard-kill with no further traffic.** A conversation whose placeholder was left by a
     SIGKILLed/OOM-killed turn and that receives no further turn is only resolved by the
     reconcile sweep while the row is the newest message and within
     `reconcile_max_age_seconds` (24 h). Recommend a bounded janitor pass in the reconcile
     sweep (resolve BOT/PENDING rows older than the grace period without the max-age cap).
  2. **Redis down at hand-off time.** If the hand-off enqueue fails the newest message
     waits for the next inbound (logged as `newest-inbound hand-off failed`); the ingress
     already surfaces enqueue failures as 503, and this path has no other recovery net.
  3. **Live Jev/multi-process end-to-end.** The dev-stack end-to-end turn (webhook → RQ →
     worker → Zalo) was not exercised in this session; the fix is proven at the worker-body
     level (real `_run_job_async`/`_run_job_async_inner`, real `record_bot_outcome` /
     `record_bot_pending` resolution) and is covered by the deployment smoke gate.
