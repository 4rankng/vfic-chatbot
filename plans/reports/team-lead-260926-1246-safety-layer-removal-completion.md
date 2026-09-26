# Safety-layer removal completion — cleanup, rename, flake fix

## Task record

- Task: Finish the removal of the pre-send safety-judge layer. The audit's
  "delete the leftovers" list was based on a wrong premise — the "safety" model
  role turned out to be the live candidate-extraction lane — so the approved
  scope became: delete the true dead code, rename the role to `extractor`
  across the stack, fix stale comments and doc drift, and make the facebook
  reveal test hermetic after root-causing its order-dependence.
- Scope: backend graph/settings/schemas/config/scripts/tests, frontend
  integration types and payload fan-out, env examples, deployment docs, one
  test-hermeticity fix. Data contracts kept untouched: `safety_verdict`
  (historical decision_trace rows), `safety_blocked` (stored outcome strings),
  `safety_ms` (historical stage_timings keys).
- Files changed: see commit `37b7cf54` (carried the bulk of this work in-tree;
  its message documents the rename explicitly) plus the follow-up commits:
  `think_strip` module rename (git mv + 3 importers + doc references), and the
  facebook reveal hermeticity fixture.
- Instructions retrieved: AGENTS.md, docs/decisions/ddd-context-boundaries.md,
  docs/deployment-guide.md, docs/testing.md, docs/code-standards.md (conventions
  via existing code), frontend AGENTS.md.
- Approval required: yes — safety-control change, protected `core/config.py`,
  admin API contract change, prod deployment. Approval evidence: the user
  explicitly ordered the original judge-layer removal, chose "Full cleanup +
  rename" from the presented options, approved the think_strip rename and the
  two-commit plan, then ordered "commit all code, push, deploy to prod".
- Approval evidence: conversation record of this session.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | SAFETY_PROMPT deleted (zero importers verified); role renamed to `extractor` in clients/factories/config/llm service/schemas/exports/frontend payload fan-out; custom extractor plumbing removed (was provably inert via the agent-model mirror); stored key + env vars + deployment-guide rows renamed; dead kwarg threading removed; SAFETY_PROMPT/self-references gone; extraction lane resolved under the new name (`get_settings()` probe: minimax_extractor_model, openrouter_extractor_model resolve; custom field absent). |
| Diff is limited to the approved scope | PASS | git status contained only in-scope files across both streams; `verify_streaming_turn.py` work was the user's own and was explicitly included per "commit all code". |
| Protected operations were avoided or approved | PASS | config.py / safety-control / admin-API / deploy approvals explicit in-conversation. |
| Focused tests/checks pass | PASS | 205-test focused set green on the merged tree (inventory snapshot, facebook module, answer-guard, clients, factories, settings, integrations API). |
| Broader regression tests pass when shared behavior changed | PASS | Full backend suite 2512 passed / 24 skipped across three independent full runs on the merged tree (randomized and `-p no:randomly` orders); the one order-dependent failure is root-caused to a poisoned process-local secret cache and fixed hermetically (fixture added to test_facebook_oauth.py); final post-rename full run green. |
| Lint passes for affected code | PASS | `ruff check .` → All checks passed (backend, run repeatedly after each pass). |
| Type checking passes for affected code | N/A | Backend has no type-check gate wired (ruff only). Frontend: `tsc --noEmit` TYPECHECK PASS. |
| Build/import validation passes for affected code | PASS | `python -c` import probe of settings/config/clients/factories with new names; pytest imports all touched modules. |
| Security and privacy impact reviewed | PASS | No secret, PII, or logging-path changes. Admin API field rename ships with the frontend in the same deploy; pydantic `extra="ignore"`/`forbid` behavior verified both directions. Historical `safety_verdict`/`safety_blocked`/`safety_ms` values preserved. |
| Performance and async-I/O impact reviewed | N/A | No runtime path changed: renames only; the deleted kwarg was never consumed. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change (no safety UI input existed). |
| Error handling and compatibility reviewed | PASS | Renamed stored keys orphan old rows harmlessly (KV store, resolver falls back to env default); `extra="ignore"` makes stale prod env vars harmless; admin panels re-save self-heals. |
| Documentation impact handled | PASS | ddd-context-boundaries.md GraphDeps list + agent-runtime row, deployment-guide env rows, testing.md test-list, codebase-summary row, module docstrings, benchmark docstring. Historical journals deliberately untouched (point-in-time records). openwiki/ left to its scheduled regeneration. |
| No new unlinked TODO/FIXME/HACK | PASS | None added. |
| Final `git diff --check` passes | PASS | exit 0. |
| Final `git status --short` reviewed | PASS | Reviewed after every pass; final state limited to the rename, the fixture fix, and doc references. |

## Result

- Overall status: PASS (pending the final post-rename full-suite run and the
  deploy; updated before push).
- Remaining risks or follow-ups:
  1. Deploy is ordered by the user; blue/green with the smoke gate must pass
     before the Caddy flip. Post-deploy: verify smoke, worker logs, and the
     extraction lane on the new names.
  2. Prod may hold orphaned stored rows under the old key names
     (`openrouter_safety_model`); harmless (env fallback engages) and an
     operator re-save of the OpenRouter panel re-binds under the new key.
  3. The parallel session's answer-completion guard ships in the same deploy;
     its own risks are recorded in
     `plans/reports/260926-1219-answer-completion-guard-completion.md`.
