# Agent Completion Checklist

## Task record

- Task: Recruiter-triggered bot review turn — an icon button in the conversation
  console that makes the LLM read the conversation and answer only if it should.
- Scope: New `POST /api/v1/conversations/{id}/bot-reply` transport; a
  `manual_reply` turn contract in `app/graph/`; the scheduler producer; the
  console icon button, its action, provider method and message catalog.
  Deliberately NOT in scope: changing `force-bot-reply` (the pending-inbound
  nudge), any change to the agent's reply policy for ordinary inbound turns,
  and any change to how a candidate-initiated turn is enqueued.
- Files changed: `backend/app/graph/manual_reply.py` (new),
  `backend/app/graph/{lanes,prompt_context,runner,types}.py`,
  `backend/app/services/conversation/scheduler.py`,
  `backend/app/api/conversations.py`, `backend/app/workers/chatbot_worker.py`,
  `backend/tests/test_manual_bot_reply_turn.py` (new),
  `backend/tests/test_runtime_surface_inventory.py` +
  `backend/tests/fixtures/universal_platform/runtime_surface_inventory.json`
  (inventoried-surface deltas), `docs/architecture/api.md`,
  `docs/architecture/system-architecture.md`, and the frontend files
  (`dataProvider.ts`, `use-conversation-actions.ts`, `ChatThread.tsx`,
  `untitledui-conversations.css`, `vietnameseCrmMessages.ts` + 2 test files).
- Instructions retrieved: `AGENTS.md` (task routing: implementation →
  `docs/development/code-standards.md`), `standards/agent-completion-checklist.md`,
  `backend/tests/test_architecture_boundaries.py`,
  `backend/tests/test_runtime_surface_inventory.py`.
- Approval required: Yes — deploy to production.
- Approval evidence: User instruction "once done commit push and deploy"
  (2026-10-08), plus the standing repository workflow for
  `make release-check` → push → `make deploy` (blue/green, smoke-gated).

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `POST /{conv_id}/bot-reply` enqueues a turn with no inbound and `manual_turn=True` (`app/api/conversations.py:341`, `app/services/conversation/scheduler.py:48`); the agent receives the review directive in the mandatory-instruction slot (`app/graph/lanes.py:1108`), may return `NO_REPLY`, and that becomes a `manual_skip` suppression that sends nothing (`app/graph/lanes.py:1179`). Console icon button renders beside "Tiếp quản" in bot mode (`ChatThread.tsx:664`) and calls the new endpoint. |
| Diff is limited to the approved scope | PASS | `git status --short` reviewed: this commit touches only the files listed above. Four concurrent-session files (`app/graph/ports.py`, `app/graph/tools/tingting_identity.py`, `app/services/retrieval/repository.py`, `app/services/tingting_api.py`) are unrelated work-in-progress and were deliberately excluded from the commit. |
| Protected operations were avoided or approved | PASS | No deploy without approval; no branch/PR/merge. Blue/green deploy is gated by `make release-check` and the droplet smoke check (`scripts/smoke_turn.py`). |
| Focused tests/checks pass | PASS | `pytest tests/test_manual_bot_reply_turn.py` → 29 passed (sentinel parsing, directive, lane skip, prompt rendering, scheduler job shape/lock handling, route guards). Frontend: `vitest` on `ChatThread.test.tsx` + `useConversationActions.test.tsx` → 56 passed. |
| Broader regression tests pass when shared behavior changed | PASS | Backend `pytest -m "not integration"` → 3914 passed, 28 skipped; the single failure (`test_broad_side_effect_scan_matches_reviewed_boundary_snapshot`) is caused by the concurrent session's Redis call, not this change (verified: in a clean worktree containing only this change, `test_runtime_surface_inventory.py` + the new tests → 34 passed). `test_architecture_boundaries.py` → 21 passed. Frontend full app suite → 1036 passed / 120 files. |
| Lint passes for affected code | PASS | `backend/.venv/bin/ruff check .` → "All checks passed!". `npm run lint` → 0 errors (35 warnings, all pre-existing `react-refresh` notices in untouched illustration files; no finding in any touched file). |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` clean for the changed graph modules (part of `make release-check`); `tsc --noEmit --project tsconfig.app.json` → exit 0. |
| Build/import validation passes for affected code | PASS | `npm run build` (`tsc && vite build`) → built, PWA service worker generated. |
| Security and privacy impact reviewed | PASS | Route uses the same `get_current_user` JWT dependency as the sibling nudge; the mode guard still refuses a recruiter-owned thread, so a recruiter cannot use it to send into a conversation another recruiter owns. No message content, phone number, or secret is logged; the skip path logs only the conversation id and trace id. The directive carries no candidate data. |
| Performance and async-I/O impact reviewed | PASS | The route does one lock acquire + one queue enqueue, mirroring the existing nudge (sync Redis behind the same composition seam). Progressive send is deliberately disabled for review turns — the early sender could deliver a bubble before the reply-or-silence decision exists, which would break the contract. Lock TTL is released when the enqueue is refused, so a failed click cannot strand the chat. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Icon-only button carries `aria-label` "Cho bot đọc hội thoại và trả lời nếu cần" plus a Radix tooltip with the same text; 40×40 icon-button target in a 38px-tall row; disabled/loading states mirror "Tiếp quản"; success/error feedback uses the Vietnamese catalog (`conversations.bot_reply.*`). Hidden in human/claim mode, where the bot must not speak. |
| Error handling and compatibility reviewed | PASS | A held conversation lock returns 409 "Bot đang xử lý hội thoại này…" rather than a misleading "nothing to answer"; a taken-over thread returns the existing 409. `BotRunState.manual_instruction` defaults to `""`, so every existing job and test is unaffected; jobs without `manual_turn` resolve to an empty directive. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/architecture/system-architecture.md` gained a "Recruiter-requested review turns" section (new turn kind + `manual_skip` outcome); `docs/architecture/api.md` route row now lists bot-reply nudges. `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | No such markers added in the diff. |
| Final `git diff --check` passes | PASS | `git diff --check` → no whitespace errors. |
| Final `git status --short` reviewed | PASS | Reviewed; the concurrent session's four unrelated modified files were identified and excluded rather than committed. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - The skip decision is the model's. The directive asks for `NO_REPLY` when
    nothing is warranted, but a live model could still answer a thread that did
    not need it; the sentinel check also accepts the separator-free spelling so a
    variant can never be sent verbatim to a candidate.
  - A review turn that the model answers produces a normal SENT outcome, so it is
    indistinguishable in the dashboard from an inbound-driven reply apart from
    `stage_timings.execution_source = "manual"`.
  - `test_broad_side_effect_scan_matches_reviewed_boundary_snapshot` currently
    fails in the shared working tree because of the concurrent session's
    uncommitted TingTing identity store; that session must recompute the broad
    digest when it lands its change.