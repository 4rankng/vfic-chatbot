# OPS-28 — Migration chain reversibility: already fixed at HEAD; all acceptance criteria re-verified 2026-09-28

## Outcome

**The card's two defects are already fixed in HEAD and I re-proved every acceptance
criterion against a fresh throwaway database today. No code changes were needed.**

The entire scope of this task was executed and committed on 2026-09-27 19:22 +0800 as
`44e8ed05` ("fix(migrations): make the chain reversible, and stop it corrupting published
documents"), which is an ancestor of the current HEAD (`39fde21d`). The commit touched
exactly the files this task owns: `0005_remove_knowledge_approval_gate.py`,
`0006_publish_knowledge_status.py`, `0042_installation_revision_lifecycle.py`,
`0043_installation_setup_draft.py`, `0044_generic_contact_case_kernel.py`, and
`tests/integration/test_migration_roundtrip_walk.py` (+78 lines there). The dispatch
likely crossed with that earlier session's landing.

My work today: independent verification, not re-implementation. I edited nothing.

## Which option was chosen for PUBLISHED ownership, and why it is right

`44e8ed05` chose **option 1: 0006's downgrade owns the label by keeping `PUBLISHED`
in the enum** (i.e. 0006's downgrade no longer drops it). The committed reasoning,
which I verified against 0001:

- `0001_baseline` creates `knowledge_status` **with** `PUBLISHED` already in it
  (UPLOADED, PROCESSING, PUBLISHED, ARCHIVED, FAILED). The approval labels
  (`READY_FOR_REVIEW`, `APPROVED`, `REJECTED`) that 0006's old downgrade restored never
  existed in any database built by this chain.
- Therefore 0006's upgrade is a no-op on the enum's label set, and its downgrade now
  recreates the identical label set — the downgrade of each revision is written against
  the schema state the previous revision in the reverse walk actually leaves behind,
  which is exactly the card's acceptance framing.
- 0005's downgrade (`WHERE kd.status = 'PUBLISHED'`) runs after 0006's in the reverse
  walk, and `PUBLISHED` still exists there, so its predicate is valid. Its comment now
  documents this dependency explicitly.
- Bonus defect the fix caught: the old 0006 downgrade did not merely break the walk —
  on real data it rewrote every `PUBLISHED` row to `APPROVED`, a value the application
  cannot produce. Keeping `PUBLISHED` also fixes that silent data corruption.

This matches the card's option 1 and is the honest choice; option 2 (making 0005 stop
filtering on `PUBLISHED`) would have changed pre-0005 retrieval semantics.

## Offline `--sql` fix (defect 2)

`0044`'s downgrade guard is now a plpgsql `DO $$ ... RAISE EXCEPTION ... $$` block
(`_data_refusal_sql()` at backend/alembic/versions/0044_generic_contact_case_kernel.py:461):
it raises identically online — before any DDL, inside the migration transaction — and
renders as ordinary SQL offline, where it fires at apply time. The same defect class was
present in `0042` and `0043`; both got the same in-place fix in the same commit, which is
within this task's same-class stop condition. A grep over `alembic/versions/` confirms no
live `connection.scalar(SELECT EXISTS ...)` guard remains anywhere in the chain (the only
grep hits are the three docstrings explaining the history).

## Walk evidence (run 2026-09-28, this session)

Throwaway database `kanban_ops28_tmp_71806` created on the dev Postgres
(`localhost:5443`, service `backend-postgres-1`), dropped in the same run's `finally`.
No pre-existing database was touched; the two `vfic_integration_walk_*` databases that
exist on the server predate my session and were left alone. My earlier aborted probe
(`kanban_ops28_tmp_69658`, wrong base revision id) was also dropped by its own cleanup.

- `alembic upgrade head` → rc=0; `alembic current` → `0057_drop_match_memories_vector_overload (head)`
- `alembic downgrade 0001` (the chain's base revision — the deepest legal rollback
  target) → rc=0; `current` → `0001`
- `alembic upgrade head` → rc=0; `current` → `0057_drop_match_memories_vector_overload (head)` — same head
- `alembic downgrade head:0001 --sql` → rc=0, 1802 lines of SQL rendered, no
  `AttributeError`; tail: `-- Running downgrade 0002 -> 0001 / ALTER TABLE public.users DROP COLUMN token_version; ...`
- Literal `alembic downgrade base` → rc=1, failing **only** at
  `0001_baseline.py:625` with its deliberate forward-only `RuntimeError` ("greenfield
  baseline is not reversible"), after every real downgrade had applied — `current` showed
  `0001` at that point, versus the card's original failure at `0005`. `alembic upgrade head`
  recovered to `0057` cleanly.

**Nuance on the acceptance criterion "`downgrade base` completes":** literal `base`
means "one step *past* the base revision", and 0001's downgrade raises on purpose — it is
a documented forward-only greenfield baseline (`0001_baseline.py:622-628`). The deepest
state any rollback can legally reach is revision `0001`, and the full walk to it completes
and re-applies. This is the repo's pre-existing, documented design, not a defect of the
class this card describes, and the extended test encodes exactly this reasoning in its
docstring. Changing 0001 to be reversible is out of scope for this card.

## Test evidence

- `pytest tests/integration/test_migration_roundtrip_walk.py -p no:randomly -m integration`
  → **3 passed** in 1381.72s (23:01). The file already contains the requested extension as
  of `44e8ed05`: `test_chain_reverses_to_base_and_reapplies` (head → base revision → head,
  asserting the revision after each leg) and `test_reverse_chain_renders_offline`
  (`head:base-revision --sql`). It also runs `test_every_migration_roundtrips_in_sequence`
  (per-revision upgrade / downgrade -1 / upgrade over all 57 revisions) with
  `KNOWN_BROKEN_DOWNGRADES` empty — the walk found zero broken downgrades, so no
  additional same-class fixes were needed and the stop condition never triggered.
- `.venv/bin/ruff check alembic` → all checks passed. (Also clean on the test file.)

## Files modified by me today

None. All task-owned files already carry the fix at HEAD; working-tree changes currently
visible in `git status` (Makefile, `backend/app/graph/*`, `docs/ops/deployment-guide.md`,
kanban moves) belong to other teammates, and I touched none of them.

## Unresolved questions

- None blocking. For the lead: the Makefile gate ("the gate should invoke the walk") is
  the lead's follow-up — note the per-revision walk test alone takes ~20 minutes, so the
  gate may want only `test_chain_reverses_to_base_and_reapplies` +
  `test_reverse_chain_renders_offline` (~2–3 minutes) rather than the whole file.

Docs impact: none — the chain's behavior now matches what the already-committed migration
docstrings and test docstrings record; no user-facing workflow, command, or architecture
surface changed today.
