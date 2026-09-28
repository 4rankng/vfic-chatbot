# Kanban TODO batch — team run, integration, and production deploy

2026-09-28, 18:22–20:55 SGT. A four-developer Agent Team (ops29-lead-types,
ops30-graph-types, ops28-migrations, sec12-doc19-gates, all fullstack-developer
on Sonnet) ran the six TODO cards with disjoint file ownership in the shared
tree; the lead integrated, verified, committed, pushed, and deployed.

## Outcome

All six TODO cards are handled and the batch is live in production.
`make release-check` passed twice end-to-end (once standalone, once inside
`make deploy`), the blue/green cutover flipped to web-green at tag `10366b03`
with every container healthy, and `efc8cecb..10366b03` is pushed to origin.
Rollback if ever needed: `make rollback`.

| Card | Result |
|---|---|
| SEC-12 | Implemented: `npm audit --omit=dev --audit-level=high` gates `release-check`; exclusions and the GitHub-vs-lockfile reconciliation recorded in `docs/ops/deployment-guide.md` §3. |
| OPS-29 | Implemented: the card's four Pyright errors were already fixed at HEAD by parallel-session commits `0e6c0747`/`8f49f29d`; the live gap was the Semgrep audit noise, silenced with the verified short-form `# nosemgrep: avoid-sqlalchemy-text` (the registry serves the rule id doubled, so the card's prescribed long form can never match). pyright 0, 227 lead tests green. |
| OPS-28 | Verified only: the owner had fixed the chain themselves in `44e8ed05` (2026-09-27 19:22), including a data-corruption fix the card had not found (0006's old downgrade rewrote PUBLISHED rows to APPROVED). Independently re-proven on a throwaway DB: head → 0001 → head, offline `--sql` renders, 3/3 integration tests. `downgrade base` stops only at 0001's by-design forward-only raise. |
| OPS-30 | Implemented: `app/graph` from 52 live Pyright errors to 0, no ignores. Four drifted literals joined `DecisionTraceSummaryCode` in `schemas/bot_run.py` after triage (record_decision is an inert compatibility sink); `TurnRoute.reason` is Literal-typed. `backend/pyrightconfig.json` binds the venv; a scoped pyright gate and the fast migration-walk subset now run in `release-check`. |
| DOC-19 | Resolved upstream: the owner restored AGENTS.md + standards/ and shipped `check-doc-links.mjs` in `d92c1584`, minutes after the card was opened. The team caught its own stale premise before touching anything. |
| OPS-31 | Bookkeeping: fix had shipped in `39fde21d`; card moved TODO → QA_TESTED per its own frontmatter. |

## Verification

The lead re-ran every teammate claim rather than trusting completion messages:
pyright 0 on both packages (venv-bound), ruff clean, 227 lead tests, 139
runner-turn + architecture tests, the two fast migration-walk tests (117 s),
the stale `test_runtime_surface_inventory` snapshot reproduced and re-keyed
against a throwaway worktree at `39fde21d^` (the −2 provider_boundary rows are
exactly `probe_zalo_oa_channel`'s own get/post sites, removed by the OPS-31
fix; 90→88, digest recomputed, reason documented in the file's convention).
16-gate completion records per the restored constitution were filed for the
three implementation tasks.

## Commits

`79847ab6` feat(release) audit gate · `f18ee98f` chore(lead) semgrep
annotations · `5f4c9d50`+`3baee1ac` docs(kanban) close-outs · `42303a08`
refactor(graph) pyright zero · `8e8467cb` test(inventory) snapshot re-key ·
`3c3d286d` feat(release) pyright + migration-walk gates · `10366b03`
docs(deploy) gate documentation.

## Deploy

`make deploy` on the committed tree: its own gate run green, pre-deploy backup
taken, both images built and pushed (`tinghire-be`/`tinghire-fe:10366b03`),
`bg_deploy.sh` cutover to web-green, pipeline verified (consumers live, no
conversation awaiting a reply, outbox drained), frontend recreated. Post-flip
`make -C backend deploy-status`: all services healthy on `10366b03`. Note: this
deploy also carried `39fde21d` (this morning's zalo diagnostics/link fixes),
which had been committed but never deployed. The OA profile backfill that
`bg_deploy` restarts reported 62/62 profiles unreachable from the droplet —
it retries idempotently and is unrelated to this batch; flagged for a look.

## Deviations worth keeping

- The release gate is no longer purely "unit-only / never needs local dev
  infrastructure": the migration-walk gate needs the dev Postgres. The
  deployment guide now says so.
- `git mv` carries the index blob, not working-tree edits — card status edits
  made before a column move need their own `git add`; landed as `3baee1ac`.
- Two of four cards were stale relative to parallel-session commits; the
  verify-don't-re-fix instinct saved the batch from double-fixing.
