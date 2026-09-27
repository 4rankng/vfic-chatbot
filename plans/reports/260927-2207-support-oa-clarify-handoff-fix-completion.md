# Support-OA handoff fix + clarify-first policy — completion

## Task record

- Task: On the TingTing support OA, (a) fix the production defect where the
  handoff reply was recorded SUPPRESSED ("Đã chặn" in the console) and never
  reached the employee, and (b) replace "any non-reset message waits for a
  human" with "the bot asks which problem the employee has, then either runs the
  password-reset flow or hands off with the fixed consultant line".
- Scope: `backend/app/graph/lanes.py`, `backend/app/graph/router.py`,
  `backend/app/graph/tingting_guide.py`, `backend/app/schemas/bot_run.py`,
  `backend/app/services/conversation/{bot_path,service,state}.py`,
  `backend/scripts/smoke_turn.py`, `backend/tests/test_graph_runner_turn.py`,
  `backend/tests/integration/test_support_handoff_reply_send.py` (new),
  `docs/architecture/system-architecture.md`,
  `docs/decisions/0013-zalo-multi-oa-accounts.md`.
  Excluded: frontend, migrations, dependencies, webhooks/auth/config, the
  recruitment channel's routing, offline Jev verification (no harness/credential).
- Files changed: the 12 paths above (11 modified, 1 added).
- Instructions retrieved: `AGENTS.md`, `.claude/CLAUDE.md`,
  `.claude/rules/primary-workflow.md`, `.claude/rules/review-audit-self-decision.md`,
  `.claude/rules/documentation-management.md`, `standards/agent-completion-checklist.md`,
  `docs/decisions/0013-zalo-multi-oa-accounts.md`,
  `docs/architecture/system-architecture.md`.
- Approval required: yes — `backend/app/graph/tingting_guide.py` is injected bot
  prompt text, and `lanes.py` changes bot-turn behavior (AGENTS.md "changing bot
  prompts"). No migration, webhook, auth, dependency, or protected-path change.
- Approval evidence: product owner in-session — the reported symptom ("wtf
  message is blocked? can't chatbot support user properly"), the requirement
  ("bot need to identify what user want first, 'Tôi cần hỗ trợ' bot should ask
  what user problem first"), the chosen mechanism ("LLM agent should clarify"),
  and the chosen policy ("A": clarify on unclear intent, hand off only on a
  confident non-support intent). Then "fix all issues, commit, push".

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Employee is asked which problem they have (`support-oa-clarify` probe → `outcome='sent'`, reply delivered, `mode=BOT`, no escalation); a confident non-support question still hands off and the line is now delivered (`support-oa-handoff` probe → `outcome='sent'`, `mode=HUMAN`, note written). Root cause of the suppression removed: `escalate_extracted_intent(preserve_turn_ownership=True)`. |
| Diff is limited to the approved scope | PASS | `git diff --stat`: 12 files, 456 insertions / 53 deletions; every path is in Scope. `.claude/CLAUDE.md` (Repowise-generated block, allowed by `Makefile:48`) is intentionally left uncommitted. |
| Protected operations were avoided or approved | PASS | No `backend/alembic/versions/`, webhooks, auth, `config.py`, dependency manifest, deployment file, or `Makefile` change (`git status --short`). Prompt-text change in `tingting_guide.py` approved in-session (see Approval evidence). |
| Focused tests/checks pass | PASS | `pytest tests/integration/test_support_handoff_reply_send.py tests/integration/test_extraction_intent_escalation_concurrency.py tests/integration/test_outbound_finalize_lock_race.py` → 7 passed. `pytest tests/test_graph_runner_turn.py -k "support_oa or tingting or off_channel"` → 7 passed (3 new clarify params). `python -m scripts.smoke_turn` → 5/5 probes OK. Negative controls: with the handoff flag reverted the smoke probe reports `outcome='suppressed'`; with the clarify branch disabled the `support-oa-clarify` probe fails on the delivered body. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -m "not integration"` → 2699 passed, 28 skipped, 144 deselected. Backend release gates: `benchmark_rag.py --gold` 54/54 (golden_pass_rate_pct=100.0), `release_gate_check.py` passed. Alembic heads = 1 and matches `docs/ops/deployment-guide.md` (0057). `uv lock --check` resolved 93 packages. `node scripts/check-agent-rules-committed.mjs` OK. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check .` (release-check body) and a targeted run over all changed Python files → "All checks passed!". |
| Type checking passes for affected code | N/A | Backend has no configured type checker (`release-check` runs ruff + pytest only); the frontend typecheck covers untouched code. |
| Build/import validation passes for affected code | PASS | `.venv/bin/python -c "import app.main, app.graph.lanes, app.graph.router, app.services.conversation.service, scripts.smoke_turn"` → `IMPORT OK`. |
| Security and privacy impact reviewed | PASS | The clarify rule explicitly forbids requesting personal data in that turn and keeps the existing PII rules (never read back name/CCCD/phone). No new data surface, no token/secret access, no logging of message content. The claim guard is not weakened: a newer inbound still loses the claim (integration test 2). |
| Performance and async-I/O impact reviewed | PASS | No new I/O, DB round trip, or allocation on the hot path; the only added cost is one model turn for an *unclear* support-OA message that previously produced a canned line. No `await` removed: `ConversationService.recheck_ownership` gained the `await` it was missing (removes a per-turn `RuntimeWarning` and restores the pre-send guard). |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | No UI change (frontend untouched). New Vietnamese copy follows the guide's existing operator-approved wording, and the clarify question asks one short question per turn. |
| Error handling and compatibility reviewed | PASS | `preserve_turn_ownership` defaults `False`, so the extraction job keeps bumping `version` and releasing the lock; a degraded/unavailable Jev still routes to the clarify branch; the handoff stays best-effort (exception swallowed, reply unaffected). The new trace literal is additive in `_DECISION_CODE_SUMMARIES`. |
| Documentation impact handled | PASS | `docs/decisions/0013` point 6 rewritten + amendment + status note; `docs/architecture/system-architecture.md` §11.2 serving bullet and §14b routing bullet updated; `node scripts/check-doc-links.mjs` → "Agent routing OK: 55 paths and 4 make targets across 5 documents all resolve." |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -n "TODO\|FIXME\|HACK"` over every changed Python file → none. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Only the 12 scoped paths (+ `.claude/CLAUDE.md`, generated block only, uncommitted by intent). |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - Jev's own verdict for "Tôi cần hỗ trợ" was not observed: the only end-to-end
    `/decide` exercise is `tests/test_golden_set.py`, opt-in via `JEV_EVAL=1` +
    `JEV_API_KEY` and network. Every lane behavior for a given verdict is covered.
  - A message that is really a recruitment question but that Jev reads as
    `general` gets the clarifying question first; the employee corrects it and the
    next turn hands off. One extra round trip, no wrong action.
  - The support-OA system prompt is still the recruitment persona plus the active
    project index (pre-existing; the TingTing guide is appended). Re-framing that
    prompt is a separate, prompt-approved change.
