---
date: 2026-07-15
session: universal-installation-lifecycle
---

# Journal: 2026-07-15 — Universal installation lifecycle

## Context

The universal-platform plan requires one deployable image that starts without
customer, industry, persona, template, or sample defaults. Phase 2 established
the immutable lifecycle authority. Phase 3 added a PostgreSQL-backed authoring
workspace and a pre-Admin setup experience, while intentionally leaving
production activation disabled until later phases consume the new contracts end
to end.

## What Happened

- Added a code-owned capability registry whose selected-pack contract hash is
  independent of unrelated industry packs. Database settings select allowlisted
  identifiers; they cannot define executable plugins, prompts, code, SQL, or
  import paths.
- Added append-only installation revisions, validation evidence, immutable
  persona versions, and a singleton lifecycle pointer with monotonic revision,
  lock version, and `authority_generation`. Migration `0042` inserts no business
  or activation data and has a verified empty upgrade/downgrade roundtrip.
- Added transactional draft, validate, activate, rollback, suspend, and resume
  services and eight admin/runtime endpoints. Public runtime output is an
  allowlisted projection; secrets and private policy/persona content remain
  excluded.
- Added a canonical runtime authority fingerprint covering the active manifest,
  generation, persona, workflow, provider policy, templates, pack contract, and
  active knowledge-base vector. PostgreSQL remains authoritative; Redis is only
  a best-effort cache.
- Independent review hardened concurrent saves with optimistic locking, replaced
  arbitrary policy objects with closed typed policies, and made readiness a live
  check against current evidence rather than a stored historical claim. It also
  tightened database identifiers and checksums, validated locale/timezone/currency
  values, and locked operational tables while activation checks compatibility.
- Additional review fixes serialized persona successor allocation, rejected
  duplicate activation, tolerated cache invalidation failure after commit,
  rejected forged cache evidence, preserved append-only content when actor FKs
  are nulled, and reran contamination checks inside the activation lock.
- Added an empty singleton setup-draft model, strict seven-section draft schema,
  code-owned catalogs, optimistic concurrency, and atomic finalization into an
  immutable validated revision. The migration inserts no business rows.
- Added a direct, `no-store`, fail-closed frontend bootstrap before React Admin.
  Pre-active states mount an account/setup-only shell with no business resources,
  dashboard, or realtime connection.
- Added the admin setup flow for identity, pack, regional terminology, workflow,
  templates, persona, integrations, and review. Inputs start blank, secrets go
  directly to encrypted integration settings, and activation remains disabled.
- Independent frontend review found that the legacy persona-create default would
  silently add recruitment follow-up schedules. Setup now requires an explicit
  disabled choice and stores no cadence or eligible recruitment stage; legacy
  create defaults remain unchanged for compatibility until the later capability
  migration.

## Reflection

An admin-configurable manifest is useful only if it is also an authority
boundary. Immutable revisions and monotonic generations make rollback auditable
without reviving stale work, while optimistic concurrency prevents one Settings
session from silently overwriting another. Typed policy schemas and strict public
projections keep frontend configurability from becoming an unbounded or secret-
bearing execution surface.

The most important safety decision was to keep the recruitment pack marked
`runtime_ready=False`. Phase 2 provides durable contracts, but the existing bot
still consumes the legacy current-persona projection and active knowledge-base
writers do not yet advance the installation authority. Allowing activation now
would advertise guarantees the runtime does not yet enforce.

The setup shell is intentionally separate from the active application. Hiding
links inside the existing CRM would still mount business resources and could
leak cached customer state. Resolving the public runtime projection before Admin
composition gives clean installs a neutral, database-authoritative path and
makes network or schema failure block the workspace rather than revive a browser
fallback.

## Decisions Made

| Decision | Rationale | Impact |
|---|---|---|
| Store immutable revisions and validation evidence | Configuration must be auditable and checksum-pinned | Every change creates a successor; historical authority cannot be edited in place |
| Require `expected_lock_version` on admin saves | Settings may be open in concurrent sessions | Stale saves fail instead of overwriting newer work |
| Use closed typed workflow/provider policies | Admin configuration must not accept arbitrary executable or secret-bearing JSON | Supported settings are explicit, bounded, and safely projectable |
| Recompute live readiness | Referenced persona, template, integration, or KB evidence can drift after validation | Runtime/admin status does not report stale evidence as ready |
| Lock operational tables during first activation checks | A count followed by activation otherwise races new domain writes | Compatibility evidence and pointer advancement share one database critical section |
| Keep recruitment `runtime_ready=False` | Pinned persona and active-KB writer authority are not wired yet | Production activation fails closed until later runtime phases |
| Use a mutable setup draft only for authoring | Incomplete wizard steps cannot be immutable runtime authority | Admins can resume setup while finalization remains atomic and audited |
| Mount a separate pre-active Admin shell | Normal CRM resources and realtime hooks are unsafe before lifecycle resolution | Clean setup makes only auth and setup-allowlisted requests |
| Require an explicit neutral follow-up policy | The legacy persona API otherwise injects recruitment schedules | Setup-created persona versions contain no hidden proactive behavior |

## Verification

- Phase 2 focused contract suite: 49 passed.
- Phase 2 selected disposable PostgreSQL lane: 6 passed with no skips, including
  migration roundtrip, concurrency, live-readiness drift, rollback generation,
  cache failure, safe projection, and contamination cases.
- The shared whole-worktree regression also passed 1,235 tests with 20 legacy
  skips and 11 integration tests; those broader totals include unrelated
  concurrent changes in the working tree.
- Ruff passed.
- Phase 3 backend suite: 1,222 passed with 20 legacy skips; focused setup,
  lifecycle, concurrency, migration, and persona lanes passed, including real
  PostgreSQL coverage. The follow-up policy correction added 11 focused passes.
- Phase 3 frontend: lint and typecheck passed; production build passed; the full
  browser project passed 321 tests and the Node project passed 93 tests.
- Independent backend re-review passed after duplicate template-version
  references were rejected before checksum normalization. Independent frontend
  review verified the bootstrap/setup boundaries and identified the neutral
  persona-policy correction above.

## Next

- Phase 4 composes bot behavior from the active manifest and its pinned persona
  version before activation can be enabled.
- Phase 5 connects every active-KB publish/rollback writer to the authority
  barrier and generation primitive.
- The codebase is therefore not universal-ready yet; Phase 2 is the fail-closed
  lifecycle foundation for the remaining work.
