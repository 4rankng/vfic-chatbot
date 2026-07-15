---
date: 2026-07-15
session: universal-installation-lifecycle
---

# Journal: 2026-07-15 — Universal installation lifecycle

## Context

The universal-platform plan requires one deployable image that starts without
customer, industry, persona, template, or sample defaults. Phase 2 established
the database and API authority needed for that model, while intentionally
leaving production activation disabled until later phases can consume the new
contracts end to end.

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

## Decisions Made

| Decision | Rationale | Impact |
|---|---|---|
| Store immutable revisions and validation evidence | Configuration must be auditable and checksum-pinned | Every change creates a successor; historical authority cannot be edited in place |
| Require `expected_lock_version` on admin saves | Settings may be open in concurrent sessions | Stale saves fail instead of overwriting newer work |
| Use closed typed workflow/provider policies | Admin configuration must not accept arbitrary executable or secret-bearing JSON | Supported settings are explicit, bounded, and safely projectable |
| Recompute live readiness | Referenced persona, template, integration, or KB evidence can drift after validation | Runtime/admin status does not report stale evidence as ready |
| Lock operational tables during first activation checks | A count followed by activation otherwise races new domain writes | Compatibility evidence and pointer advancement share one database critical section |
| Keep recruitment `runtime_ready=False` | Pinned persona and active-KB writer authority are not wired yet | Production activation fails closed until later runtime phases |

## Verification

- Backend suite: 1,235 passed; 20 legacy tests skipped.
- Disposable PostgreSQL integration lane: 11 passed with no skips, including
  migration roundtrip, concurrency, live-readiness drift, rollback generation,
  cache failure, safe projection, and contamination cases.
- Ruff passed.

## Next

- Phase 3 builds the admin Settings setup experience and removes frontend
  business fallbacks.
- Phase 4 composes bot behavior from the active manifest and its pinned persona
  version before activation can be enabled.
- Phase 5 connects every active-KB publish/rollback writer to the authority
  barrier and generation primitive.
- The codebase is therefore not universal-ready yet; Phase 2 is the fail-closed
  lifecycle foundation for the remaining work.
