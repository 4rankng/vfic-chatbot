# Completion — durable recovery net for an inbound dropped behind a turn's outcome row

## Task record

- Task: Close the residual root cause where a candidate inbound that arrives while
  a turn holds the per-chat mutex is persisted but never answered, because the
  turn's own outcome row masks the conversation from the reconcile sweep.
- Scope: `backend/app/services/conversation/repository.py` (sweep predicate),
  `backend/app/workers/reconcile_worker.py` (tick), `backend/app/main.py`
  (one `/metrics` key), plus tests. The ingress was **not** changed.
- Files changed:
  - `backend/app/services/conversation/repository.py`
  - `backend/app/workers/reconcile_worker.py`
  - `backend/app/main.py`
  - `backend/tests/test_reconcile_repository.py` (deleted the SQL-text pin)
  - `backend/tests/test_reconcile_worker.py` (2 tests added)
  - `backend/tests/integration/test_reconcile_superseded_inbound.py` (new, 16 tests)
- Instructions retrieved: `AGENTS.md`, `docs/` routing only as needed,
  `standards/agent-completion-checklist.md`.
- Approval required: none for this change (no Alembic revision, no protected path,
  no ingress change, no bot prompt/persona change, no dependency change).
- Approval evidence: `git status --short` shows only the files above; the ingress
  (`api/webhooks.py`, `services/webhook.py`,
  `conversation_messaging/infrastructure/webhook_delivery.py`) is untouched.

## Decision: option (B), with the durable link the evidence supports

**Chosen: (B) — fix the sweep predicate so a conversation whose newest candidate
message never got a turn is a reconcile candidate, using the outbound command's
`quote_message_id` as the durable link. (A) was rejected.**

Evidence chain:

1. The drop is real and unchanged: `services/webhook.py:203` returns
   `{"status": "locked"}` after the inbound was already committed at `:182`, so no
   job is enqueued for it; the Messenger ingress mirrors this at
   `conversation_messaging/infrastructure/webhook_delivery.py:74`.
2. The masking shape is the **queue-wait** drop. `record_bot_pending`
   (`services/conversation/bot_path.py:770`) creates the placeholder at turn
   *pickup*, and `record_bot_outcome` (`bot_path.py:640-660`) resolves that same
   row in place. An inbound dropped while the turn was still queued is therefore
   *older* than the outcome row, so the newest message is `BOT/SENT` or
   `BOT/SUPPRESSED` and the loop-free predicate (`repository.py:583-609`) excludes
   the conversation forever. (A drop that happens *mid-turn* is newer than the
   placeholder, so the newest message is `WORKER` and the sweep already recovers
   it — the masked shape is specifically the queue-wait drop.)
3. The shipped hand-off cannot recover it. `chatbot_worker._handoff_to_newer_inbound`
   enqueues through `enqueue_latest_unanswered_worker_message`
   (`services/conversation/scheduler.py:11`), whose test
   `latest_unanswered_worker_message` (`repository.py:406-445`) treats any
   `BOT`/`RECRUITER` row newer than the newest `WORKER` message with a
   `SENT`/`DELIVERED`/`READ` status as an answer. In the masked shape that row *is*
   the outcome that answered the older inbound, so the helper returns `None` and
   no hand-over happens. Proven against real SQL in
   `test_handoff_cannot_recover_the_masked_shape`. The shipped hand-off's own unit
   test never exercised this: its `_Svc` stub returns the newest inbound
   unconditionally (`tests/test_chat_turn_handoff.py:66-67`).
4. A durable, non-timestamp link exists — and it is the only one. Every turn
   records the inbound it answered as the `quote_message_id` of the outbound
   command it writes with its outcome
   (`graph/runner.py:1040-1046,1096-1099` → `_build_outbox_payload` →
   `record_bot_outcome` → `outbound_outbox.payload`), and that payload is never
   rewritten. The alternatives do not identify an inbound: `messages` has no reply
   id column (baseline DDL `alembic/versions/0001_baseline.py:230-241`, plus 0045
   and 0047), and `bot_runs.version_at_start` is a conversation version that
   recruiter actions also bump (`recruiter_path.py:97,153,212,251,268,311,368,416`),
   so a version comparison would mis-fire and re-answer answered conversations.
5. Therefore (A) was not needed and was rejected: the ingress cannot schedule the
   turn itself (it cannot take the mutex the in-flight turn holds), so (A) would
   mean a new deferred job type with its own retry/dedup/backoff machinery — more
   surface, in the hot ingress path, for no additional coverage over (B).

## Change

- `repository.py`: `SUPERSEDED_OUTCOME_STATUSES` +
  `_MASKED_INBOUND_SQL` (the proof, with the full rationale in comments) + an
  `OR` branch in `find_reconcile_candidates` + `latest_inbound_never_given_a_turn()`,
  the per-conversation form the tick re-verifies with.
- `reconcile_worker.py`: new reason `superseded_inbound`, re-verified against
  freshly read state before enqueuing, counted in
  `reconcile_superseded_inbound_total`.
- `main.py`: the counter is exposed on `/metrics` next to the other canaries.
- `tests/test_reconcile_repository.py`: the `test_sql_contains_loop_free_predicate`
  source-text pin was **deleted** (it asserted `"SENT" not in sql_text` etc., i.e.
  the wording of the query, and my change invalidates it). The invariants it stood
  for are now proven behaviorally, against real PostgreSQL, in the new integration
  file — including the permanent OA-recipient rejection, in-grace exclusion, mode
  filtering and the live-lock rule it pinned by substring.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | The production shape is recovered and the suppressed shape is untouched: `pytest -q -m integration tests/integration/test_reconcile_superseded_inbound.py` → `16 passed` |
| Diff is limited to the approved scope | PASS | `git status --short`: only the 6 files above; ingress, schema, prompts, personas, dependencies untouched |
| Protected operations were avoided or approved | PASS | No `alembic/versions/*`, no `core/{config,security,ratelimit}.py`, no `api/webhooks.py`, no bot policy file, no manifest/deployment/Makefile |
| Focused tests/checks pass | PASS | `pytest -q -m "not integration" tests/test_reconcile_repository.py tests/test_reconcile_worker.py tests/test_webhooks.py tests/test_runtime_surface_inventory.py` → `59 passed` |
| Broader regression tests pass when shared behavior changed | PASS | 178 passed across the suites that touch the changed modules (`test_conversation_*`, `test_dashboard_attention`, `test_main_lifespan_cleanup`, `test_scheduler_registration`, `test_chat_turn_handoff`, `test_chat_turn_abandonment`, `test_concurrency`, `test_worker_enqueue_utils`, `test_runtime_surface_inventory`, `test_webhooks`, the two reconcile suites). The full project-wide suite was deliberately not run (assignment instruction). |
| Lint passes for affected code | PASS | `.venv/bin/ruff check .` → `All checks passed!` |
| Type checking passes for affected code | N/A | No mypy/pyright configuration in `backend/pyproject.toml` (ruff only) |
| Build/import validation passes for affected code | PASS | `.venv/bin/python -c "import app.main, app.workers.reconcile_worker, app.services.conversation.repository"` → imports OK; fragment literals and counter key verified |
| Security and privacy impact reviewed | PASS | No candidate text in any new log line (only conversation ids); the proof is built from provider message ids already stored; no new external I/O; no new endpoint |
| Performance and async-I/O impact reviewed | PASS | The fragment adds two index-backed correlated lookups per open conversation whose newest message is a completed BOT row (the sweep already scans all open conversations every ~60s); no I/O added to the turn path; `outbound_outbox.message_id` is unique, `messages_conv_created_idx` covers the newest-message lookups |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change |
| Error handling and compatibility reviewed | PASS | The tick's new branch keeps every existing reason path intact (PENDING→stale_pending, FAILED→failed_send + 900s backoff, SEND_UNKNOWN→skip unless the proof holds); the proof is re-verified before acting, so a stale scan releases the lock instead of enqueuing (`test_outcome_that_answered_the_newest_message_is_not_recovered`) |
| Documentation impact handled | PASS | Rationale documented in-place (`repository._MASKED_INBOUND_SQL`, `latest_inbound_never_given_a_turn`, `reconcile_worker` module docstring). No user-visible behavior, setup or public contract change, so no docs update |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep` over the diff shows none |
| Final `git diff --check` passes | PASS | `git diff --check` → clean |
| Final `git status --short` reviewed | PASS | 5 modified + 1 new test file (plus an unrelated untracked `kanban/` from another session, untouched) |

## Verification detail (failing before → passing after)

The new integration test was written and run **before** the implementation:

```
# before the change
$ .venv/bin/pytest -q -m integration tests/integration/test_reconcile_superseded_inbound.py
FAILED ...::test_outcome_that_answered_an_older_inbound_recovers_the_dropped_one[SENT]
FAILED ...::test_outcome_that_answered_an_older_inbound_recovers_the_dropped_one[SUPPRESSED]
FAILED ...::test_outcome_that_answered_an_older_inbound_recovers_the_dropped_one[SEND_UNKNOWN]
3 failed, 11 passed

# after the change
$ .venv/bin/pytest -q -m integration tests/integration/test_reconcile_superseded_inbound.py
16 passed
```

The three failures are exactly the production shape (WORKER `in-a` → WORKER `in-w`
→ newer BOT outcome quoting `in-a`); the 11 that passed first are the loop-safety
and guard cases that had to keep passing (suppressed-answering-the-newest-message,
no-command boundary, answered conversation, permanent OA rejection, in-grace,
past max-age, recruiter reply, HUMAN mode, live lock, plus the two fast-path
evidence tests).

## Interaction with the existing guards (verified)

- **Grace** (`reconcile_grace_seconds`): applied to the newest candidate message —
  the message the recovery turn answers — so a message that may still be handled is
  left alone (`test_in_grace_newest_inbound_is_not_recovered`).
- **Max age** (`reconcile_max_age_seconds`, 24h): same bound, so no ancient
  conversation is re-answered (`test_newest_inbound_past_the_max_age_cap_is_not_recovered`).
- **Mode**: the sweep's existing `mode IN ('BOT','SEMI_AUTO')` filter still gates
  it (`test_human_owned_conversation_is_not_swept`); the tick's
  `run_start_guard` re-check (SEMI_AUTO human takeover) is unchanged.
- **Human ownership**: a `RECRUITER` row with a delivered status newer than the
  newest candidate message excludes the conversation
  (`test_recruiter_reply_newer_than_the_dropped_inbound_wins`), and a live
  per-chat lock excludes it (`test_live_lock_excludes_the_conversation`).
- **Re-answer storm**: termination is structural, not timing-based. Once a turn
  answers the newest candidate message, that turn's own command quotes it and the
  branch stops matching; a pre-send suppression writes no command and also stops
  matching. Only one recovery turn per conversation can be in flight (the mutex is
  taken before enqueueing), and `FAILED` keeps its existing 900s backoff because it
  is deliberately not in `SUPERSEDED_OUTCOME_STATUSES`.

## Result

- Overall status: PASS (scoped), with the residual risk below.
- Residual risks or follow-ups:
  1. **Pre-send suppressions stay unlinkable.** An outcome written without an
     outbound command (lost claim / silent terminal in `graph/runner.py`, the
     worker's `LLMThrottled` path) has no durable record of the inbound it
     answered, so the sweep conservatively skips it rather than guessing —
     re-answering a deliberately suppressed turn is worse. Those shapes remain
     covered by the worker hand-off (proven in
     `test_handoff_still_covers_a_pre_send_suppression`). Closing them durably
     requires the producer change (write the command on those paths), which is
     outside this ticket's target files (`graph/runner.py`, `workers/chatbot_worker.py`);
     documented in the `_MASKED_INBOUND_SQL` comment.
  2. **Sweep cost.** The proof adds two correlated, index-backed lookups per open
     conversation whose newest message is a completed `BOT` row. Acceptable at a
     ~60s cadence over an index-backed scan; worth watching if the open-conversation
     count grows by orders of magnitude.
  3. **Messenger recovery turns** keep the existing branch's
     `reply_to_message_id = msg.zalo_message_id` (NULL for Messenger), so their own
     command may carry no quote. Harmless — the message is answered, and a missing
     quote only means the sweep will not act on that conversation again.
  4. The shipped hand-off remains a no-op for the masked shape by construction; it
     was left untouched as the fast path (its unit test's stub, not the production
     helper, is what makes it look effective there).
