# OPS-29 completion record — lead service static-analysis errors

Copied from `standards/agent-completion-checklist.md` per the restored
constitution's completion contract.

## Task record

- Task: OPS-29 — `backend/app/services/lead` live Pyright errors and Semgrep
  `avoid-sqlalchemy-text` audit triage.
- Scope: `backend/app/services/lead/` only; typing and audit annotations, no
  runtime behavior change.
- Files changed: `backend/app/services/lead/repository.py` (+6 lines: two
  bound-parameter comments plus two targeted `# nosemgrep` annotations).
- Instructions retrieved: kanban card `20260928_OPS-29-*`,
  `.claude/rules/development-rules.md`,
  `references/team-coordination-rules.md` (ak-team).
- Approval required: no — `services/lead` is not on the AGENTS.md approval-gated
  path list (migrations, webhooks, auth, bot prompts/safety, dependency
  changes, deployment files).
- Approval evidence: owner instruction of 2026-09-28 to handle all kanban TODO
  cards (team task assignment).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `uvx pyright --pythonpath .venv/bin/python app/services/lead` → 0 errors (lead re-run); `uvx semgrep scan --config r/python.sqlalchemy.security.audit.avoid-sqlalchemy-text app/services/lead` → 0 findings (was 2, teammate run). Four of the card's five diagnostics were already fixed at HEAD by `0e6c0747`/`8f49f29d` (verified ancestors of HEAD) — verified, not re-fixed. |
| Diff is limited to the approved scope | PASS | `git diff --stat backend/app/services/lead/` → repository.py only, +6 lines. |
| Protected operations were avoided or approved | PASS | No protected path touched. |
| Focused tests/checks pass | PASS | `.venv/bin/python -m pytest tests/test_lead_*.py -p no:randomly` → 227 passed (lead re-run; teammate ran the same family → 230 including two adjacent files). |
| Broader regression tests pass when shared behavior changed | PASS | No shared behavior changed (comments/annotations only); imports exercised by the test run. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check app/services/lead` → All checks passed. |
| Type checking passes for affected code | PASS | pyright 0 errors (command above). |
| Build/import validation passes for affected code | PASS | Package imported by the passing test suite. |
| Security and privacy impact reviewed | PASS | The two `text()` sites use bound parameters only; the only interpolation is the literal `EXCLUDED.`/`:` column prefix from `_merge_assignments` (card triage, re-confirmed). The registry serves the rule id doubled (`avoid-sqlalchemy-text.avoid-sqlalchemy-text`), so the long-form suppression can never match — the short suffix form `# nosemgrep: avoid-sqlalchemy-text` is the verified working form. |
| Performance and async-I/O impact reviewed | N/A | Comments only. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI. |
| Error handling and compatibility reviewed | N/A | No behavior change. |
| Documentation impact handled | PASS | None — annotations only; agent routing unchanged so `node scripts/check-doc-links.mjs` is not implicated (and passes at HEAD). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | Diff adds none. |
| Final `git diff --check` passes | PASS | No whitespace errors in the staged diff. |
| Final `git status --short` reviewed | PASS | Remaining dirty files belong to other in-flight tasks (graph package: OPS-30) and are excluded from this commit. |

## Result

- Overall status: COMPLETE
- Remaining risks or follow-ups: the pyright acceptance invocation for this
  repo's backend needs `--pythonpath .venv/bin/python`, otherwise sqlalchemy
  imports phantom-fail as missing; recorded in memory and in the narrative
  report for future static-analysis cards.
