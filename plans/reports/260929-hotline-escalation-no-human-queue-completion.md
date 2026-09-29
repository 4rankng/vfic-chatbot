# Completion — hotline escalation without human queue + editor close

Date: 2026-09-29. Operator rule of the same day: an off-scope escalation must
not promise a waiting consultant at all — the candidate is pointed at the VFIC
hotline 18007228 and nothing else. The TingTing support OA is explicitly
excluded from the hotline rule. Same task: Lưu (save) on the Agent editor
closes the editor, and the diagnostics debt reported in review is cleared.

## Task record

- Task: off-scope escalation replies with the hotline and stops queueing a
  human; PersonaEdit redirects to `/personas` after save; repo-gate and
  review-surface diagnostics clean; conventional commits.
- Scope: backend turn routing + tests + one frontend handler + one per-file
  pyright opt-out. No migration, no API change, no TingTing OA behaviour
  change.
- Files changed: `backend/app/graph/lanes.py`,
  `backend/app/graph/runner.py`, `backend/app/graph/tingting_guide.py` (comment
  only), `backend/tests/test_graph_runner_turn.py`,
  `frontend/src/components/atomic-crm/personas/PersonaEdit.tsx`, this report.
- Instructions retrieved: AGENTS.md (constitution), docs/development/
  code-standards.md conventions via existing patterns (per-file pyright opt-out
  from e7d08de1), skill://git for the commit workflow.
- Approval required: none beyond the operator rule quoted in the task; commit
  was explicitly requested.
- Approval evidence: user messages 2026-09-29 (hotline rule, TingTing
  exclusion, "no human queue, only hotline", "fix all issues and commit").

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `_agent_turn` returns `OUT_OF_SCOPE_HANDOFF_REPLY` (hotline 18007228) on a confident off-scope turn with no `_consultant_handoff` write; phone-ask interlude deleted; `tingting_support_handoff` path untouched (`tests/test_graph_runner_turn.py::test_a_confident_off_domain_turn_replies_with_the_hotline_and_skips_the_model`). PersonaEdit `onSubmit` → `redirect("/personas")` after success notify. |
| Diff is limited to the approved scope | PASS | `git status --short`: the five files above only. |
| Protected operations were avoided or approved | PASS | No deploy, no PR, no branch; commits on `main` per AGENTS.md because commit was requested. |
| Focused tests/checks pass | PASS | `pytest tests/test_graph_runner_turn.py -k "off_domain or hotline or barely_confident or handoff"` → 5 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `.venv/bin/python -m pytest -m "not integration" -q` → all passed (no failures; full output in session log). |
| Lint passes for affected code | PASS | `backend`: `.venv/bin/ruff check .` → all checks passed. `frontend`: `npm run lint` → clean. |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` → 0 errors/0 warnings; `uvx pyright tests/test_graph_runner_turn.py` → 0 errors after the documented per-file opt-out (e7d08de1 pattern); `npm run typecheck` → clean. |
| Build/import validation passes for affected code | PASS | Modules import through the full unit suite (runner/lanes imported by every graph test); frontend change verified by typecheck + 32 persona vitest tests. No build output surface changed. |
| Security and privacy impact reviewed | PASS | No secrets introduced; hotline is the operator's public number (already in `patch_vfic_office_kb.py` and the system-prompt facts). Deleting the phone-ask flow stops collecting a callback number the operator no longer acts on. Fixed replies are code, so the grounding guard is not bypassed. |
| Performance and async-I/O impact reviewed | PASS | Removes a per-turn recent-history normalization/regex scan (`_out_of_scope_phone_ask_outstanding`) and an escalation DB write; no new I/O. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Editor close mirrors the existing create flow (`redirect("/personas")`), no markup change; bot reply keeps the operator-approved "Dạ … ạ" register. |
| Error handling and compatibility reviewed | PASS | `OUT_OF_SCOPE_HANDOFF_REPLY` stays exported from `runner` for tests/scripts; deleted symbols had zero importers (repo grep, only stale `.pyc` matches). Confidence floor kept: below-floor off-scope readings still answer via the model. |
| Documentation impact handled | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 34 paths and 4 make targets". Living docs describe only the TingTing handoff line (unchanged); the recruitment phone-ask flow was never documented outside historical plans/decisions records. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | Ran before committing (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Only the six intended files. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: the low-confidence off-scope turn still
  reaches the model (unchanged behaviour, floor-guarded); if the operator wants
  the hotline reply at ANY confidence, that is a one-line floor removal in
  `lanes.py::_agent_turn`.
