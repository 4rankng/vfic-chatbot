# OPS-28 completion record — migration chain reversibility

Copied from `standards/agent-completion-checklist.md` per the restored
constitution's completion contract.

## Task record

- Task: OPS-28 — `alembic downgrade` chain cannot reach base (0006 drops
  PUBLISHED before 0005 uses it; 0044 offline `--sql` incompatibility).
- Scope: verify the chain reverses and complete the card. The fix was already
  authored by the owner in `44e8ed05` (2026-09-27 19:22, ancestor of HEAD) —
  including a data-corruption fix the card had not identified (0006's old
  downgrade rewrote PUBLISHED rows to APPROVED, a value the application cannot
  produce). This task therefore delivered independent end-to-end verification,
  not code.
- Files changed: none in code. Evidence artifacts only (this record and the
  narrative report).
- Instructions retrieved: kanban card `20260927_OPS-28-*`,
  `.claude/rules/development-rules.md`, team coordination rules.
- Approval required: migrations are a protected path. The migration edits in
  `44e8ed05` were authored and committed by the owner directly; this task made
  no migration edits.
- Approval evidence: owner commit `44e8ed05`; owner instruction of 2026-09-28
  to handle all kanban TODO cards (verification assignment).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Forward walk reverses: `upgrade head` → 0057, `downgrade 0001` → OK, `upgrade head` → same head, on throwaway DB `kanban_ops28_tmp_71806` (created and dropped; dev Postgres 5443; no pre-existing database touched). Nuance: literal `downgrade base` stops only at `0001_baseline.py:625`'s deliberate forward-only raise, after every real downgrade applied — 0001 is the documented deepest legal rollback target. |
| Diff is limited to the approved scope | PASS | No code diff produced by this task. |
| Protected operations were avoided or approved | PASS | No migration edits; throwaway database only. |
| Focused tests/checks pass | PASS | `pytest tests/integration/test_migration_roundtrip_walk.py -m integration -p no:randomly` → 3 passed (teammate, 1381.72s). Fast subset `test_chain_reverses_to_base_and_reapplies` + `test_reverse_chain_renders_offline` re-run by lead → 2 passed in 116.82s. |
| Broader regression tests pass when shared behavior changed | PASS | No behavior changed by this task; `alembic heads` → exactly one head (0057). |
| Lint passes for affected code | PASS | `ruff check alembic` clean (teammate; no changes since). |
| Type checking passes for affected code | N/A | No code changed by this task. |
| Build/import validation passes for affected code | PASS | Offline render `downgrade head:0001 --sql` → rc=0, 1802 SQL lines, no AttributeError; venv alembic binary exercised throughout. |
| Security and privacy impact reviewed | PASS | Verification used a uniquely-named throwaway database, created and dropped; no credentials or production data in evidence. |
| Performance and async-I/O impact reviewed | N/A | No runtime code changed by this task. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI. |
| Error handling and compatibility reviewed | PASS | `connection.scalar` guards replaced by offline-renderable `DO $$ ... RAISE EXCEPTION $$` blocks in 0042/0043/0044 (grep: no live `connection.scalar` remains in `alembic/versions/`); the 0001 forward-only raise is intentional and documented. |
| Documentation impact handled | PASS | None — the release gate's existing docs-drift step already pins `docs/ops/deployment-guide.md` to the Alembic head; routing unchanged. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | No code changed. |
| Final `git diff --check` passes | PASS | No whitespace errors. |
| Final `git status --short` reviewed | PASS | Remaining dirty files belong to other in-flight tasks; nothing from this task. |

## Result

- Overall status: COMPLETE
- Remaining risks or follow-ups: if the reverse walk is to be enforced on every
  release, `release-check` should invoke the fast subset
  (`test_chain_reverses_to_base_and_reapplies` +
  `test_reverse_chain_renders_offline`, ~2 min) rather than the 20-minute
  per-revision walk; the lead is adding that gate line at integration.
