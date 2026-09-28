---
id: OPS-28
title: "The migration chain cannot reach base: 0006's downgrade drops PUBLISHED, then 0005's downgrade uses it"
severity: high
area: ops
labels: [migrations, ops, release-gate]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-27
---

# OPS-28 — The migration chain cannot reach base: 0006's downgrade drops PUBLISHED, then 0005's downgrade uses it

**Severity:** high · **Area:** ops · **Labels:** migrations, ops, release-gate

**Trạng thái:** DEV_COMPLETED — the fix landed 2026-09-27 19:22 in `44e8ed05` (owner), ~30 minutes after this card was opened; it chose the keep-PUBLISHED option for 0006 and also fixed a data-corruption bug the card had not identified (the old 0006 downgrade rewrote PUBLISHED rows to APPROVED). Independently re-proven 2026-09-28 on a throwaway database: walk to 0001 and back to head, offline `--sql` renders clean, 3/3 integration tests. Literal `downgrade base` stops only at 0001's by-design forward-only raise — the deepest legal rollback target.

## Problem

`alembic downgrade base` cannot complete. The chain applies forward cleanly to head, but the reverse walk dies between 0006 and 0005 because two revisions disagree about the `knowledge_status` enum. This is not a cosmetic downgrade-script bug: it means **there is no working way to return the production database to an earlier schema state**, which is the mechanism every rollback and every "restore then migrate down" recovery procedure depends on.

## Evidence

Verified 2026-09-27 against a throwaway database on the dev Postgres (`alembic_chain_tmp_01`, created and dropped; no existing database was touched):

- `alembic upgrade head` → OK, `current = 0057_drop_match_memories_vector_overload (head)`, exactly one head.
- `alembic downgrade base` → **FAILED**, stopped with `current = 0005`:
  `invalid input value for enum knowledge_status: "PUBLISHED" ... WHERE kd.status = 'PUBLISHED'`
- `alembic upgrade head` from that partial state → OK again, `current = 0057`, one head. So the database is not bricked, but it is also not reversible.

Exact cause, across two revisions:

- `alembic/versions/0006_publish_knowledge_status.py:96-136` — the downgrade converts `knowledge_status` back to the pre-`PUBLISHED` value set (`READY_FOR_REVIEW`, `APPROVED`, `REJECTED`, …), which does **not** include `PUBLISHED`.
- `alembic/versions/0005_remove_knowledge_approval_gate.py:51` — the downgrade re-creates `public.documents` with a `WHERE kd.status = 'PUBLISHED'` predicate, referring to a label that no longer exists in the enum at that point in the reverse walk.

Both files were last written in `dce23c94` (2026-06-27). `git status backend/alembic/` is clean, so this predates the 2026-09-27 kanban sweep by three months and is not a regression from it.

A second, independent reversibility problem: the offline mode `alembic downgrade head:base --sql` dies much earlier, at `alembic/versions/0044_generic_contact_case_kernel.py:465`, with `AttributeError: 'MockConnection' object has no attribute 'scalar'`. That downgrade uses `connection.scalar(SELECT EXISTS …)` as a data-dependent guard, which cannot run in `--sql` mode. So an operator cannot even *preview* the full reverse walk offline.

## Impact

- **No tested path to an earlier schema.** The blue/green rollback in `bg_rollback.sh` flips back to the previous image and tag, so a bad migration is survivable in the common case — but that safety net depends on the old image tolerating the new schema. Anything needing a genuine schema downgrade (a bad data migration, an incident requiring a rollback below the previous release) has no working procedure, and the failure mode is discovered during an incident.
- **The release gate cannot see this.** `Makefile:41-42` checks only that `alembic heads` reports exactly one head and that `docs/deployment-guide.md` names it. Both pass today while the chain is irreversible. A card claiming the migrations are roundtrip-safe is currently false.
- The offline `--sql` preview failing at 0044 means the problem is not a single isolated revision; the chain has at least two independent reversibility defects.

## Suggested fix

Two separate changes; do not bundle them.

1. **0006/0005 enum disagreement.** Decide which revision owns the `PUBLISHED` label during the reverse walk. The honest options: have `0006`'s downgrade leave `PUBLISHED` in the enum (dropping a value that a later downgrade still references is what breaks the walk), or have `0005`'s downgrade stop filtering on the status label it can no longer assume exists. Whichever is chosen, the downgrade of each must be written against the schema state the *previous* revision in the reverse walk actually leaves behind, not against the state at the time that revision was written.

2. **0044 offline `--sql` incompatibility.** Replace the `connection.scalar(SELECT EXISTS …)` data guard with something that degrades in `--sql` mode, or document that 0044 cannot be rendered offline and give the operator the live-database procedure instead.

Then add the missing coverage: a test that walks `upgrade head → downgrade base → upgrade head` on a throwaway database and asserts the chain reverses completely. `tests/integration/test_migration_roundtrip_walk.py` already exists and already runs this walk for the range it covers — extend it to base rather than writing a new harness. Note this test is in the integration lane and is therefore **excluded from the default gate** (`pytest -m "not integration"`); if the reverse walk is meant to be enforced, the gate has to invoke it.

## Notes

- Migration edits are approval-gated per `AGENTS.md`; this card records the defect and does not authorise a fix.
- `ruff format --check` also fails on 306 files at HEAD. That is unrelated pre-existing debt, is **not** part of the repo's gate (`Makefile:54` runs `ruff check` only), and was deliberately left alone rather than turned into a reformat storm mid-sweep.

---

_Opened 2026-09-27 from the backend release-gate run during the kanban sweep. No code was changed when this was found; the throwaway database used to reproduce it was created and dropped._
