# Completion — Messenger pause actually gates the Facebook webhook path

- Task: Owner-reported: bot answered Messenger (thread aa84a8fe, 08:50–09:11 UTC 2026-10-09) despite `channel_accounts.bot_paused = t` (set 2026-10-07). Diagnose prod, fix, deploy.
- Scope: wire the existing pause check into the two dead guard points on the Messenger path. No schema, API contract, or UX change; persisted-inbound behavior untouched.
- Files changed: `backend/app/services/conversation/service.py` (bot_paused delegation), `backend/app/conversation_messaging/infrastructure/webhook_delivery.py` (pause check in enqueue_facebook_turn), plus regression tests in `backend/tests/test_conversation_service_composition.py` and `backend/tests/test_conversation_messaging_webhook_delivery.py`.
- Instructions retrieved: root AGENTS.md, docs/ops/deployment-guide.md (deploy + host layout), incident evidence from prod (DB + container logs).
- Approval required: deploy explicitly requested by owner ("do the fix then deploy").
- Approval evidence: owner message in this session.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Root causes proven on prod: (1) Facebook webhook enqueues turns with no pause check (`api/webhooks.py:513` → `enqueue_facebook_turn`); (2) runner backstop `getattr(svc, "bot_paused", None)` always None — service never exposed it. Both fixed; pause now stores messages, sends nothing. |
| Diff is limited to the approved scope | PASS | 4 files, +70/−0; two production files + two test files. Commit `1f6dad93`. |
| Protected operations were avoided or approved | PASS | Deploy is owner-requested. |
| Focused tests/checks pass | PASS | `uv run pytest tests/test_conversation_messaging_webhook_delivery.py tests/test_conversation_service_composition.py tests/test_manual_bot_reply_turn.py tests/test_reconcile_worker.py -q` → 67 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `make release-check` (backend unit lane + integration migration lane + frontend lane) green; full suite `-m "not integration"` inside release-check. |
| Lint passes for affected code | PASS | release-check backend lane: `ruff check .` green. |
| Type checking passes for affected code | PASS | release-check backend lane: `uvx pyright app/graph` green. |
| Build/import validation passes for affected code | PASS | release-check frontend lane: `npm run build && npm run smoke:built` green. |
| Security and privacy impact reviewed | PASS | No new I/O or tokens; check reads one boolean via existing session. Failure mode unchanged (fail-open on lookup error, pre-existing design). |
| Performance and async-I/O impact reviewed | PASS | One indexed boolean SELECT per Messenger enqueue only when guard passes; runner backstop reuses the same cheap query per turn. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | Paused path returns before lock/enqueue; webhook ack unchanged; manual bot replies on a paused Page now suppressed by the runner backstop (consistent with "send nothing" contract). |
| Documentation impact handled | PASS | Pause behavior docs already describe the intended semantics; this makes them true. No agent-routing change (doc-link check green in release-check). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |

## Post-deploy verification (tag `9c520c13`, web-green, 2026-10-09 ~10:05 UTC)

- A third root cause surfaced after the first deploy (`0ca2bbc8`): the lookup's
  `isinstance(row, (tuple, list))` guard assumed SQLAlchemy Row is a tuple
  subclass; on SQLAlchemy 2.0.51 Row extends Sequence, so every real lookup read
  as "not paused" — proven in-container (identical ORM query returned `(True,)`
  while `bot_paused()` returned False). Fixed in `a12eb373` + `9c520c13`.
- Prod probe: signed Messenger webhook POST for the paused Page (`486833177846024`)
  → `200 {"status":"processed"}`; message row persisted (sender WORKER);
  **zero** `run_chat_turn_job` enqueues in worker logs; **zero** new bot_runs;
  **zero** BOT messages. Runner backstop and reconcile sweep share the now-fixed
  lookup. Evidence: worker-chatbot logs (empty enqueue grep), conversations
  table counts before/after, probe mid `qa_pause_gate_a8d1281eef8d`.
- QA artifacts removed: the probe conversation was deleted from prod
  (`DELETE 1`, 0 QA conversations left); probe scripts removed from host and
  container.
- Known follow-up (out of scope here): Meta `code=10 subcode=2018300` ("another
  app is controlling this thread") when an admin acts from the Meta Business
  Suite inbox — TingTing has no handover-protocol integration, so bot sends are
  refused until control returns. Separate decision needed.
- Process note: a parallel session committed `a12eb373` (same fix, minus the
  guard completion) 30s before `9c520c13`; final code is the completed version.
  A `git stash pop` misfire during the bite-test briefly pulled an unrelated
  pre-existing stash into the tree; it was fully unwound and `stash@{0}` is
  preserved untouched.
