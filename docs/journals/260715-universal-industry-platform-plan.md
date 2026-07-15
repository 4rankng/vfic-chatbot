---
date: 2026-07-15
session: universal-industry-platform-plan
---

# Journal: 2026-07-15 — Universal industry platform plan

## Context

The codebase was evaluated for reuse across customers and industries, with each
customer deployed to a separate VPS and database. The required operating model
is frontend-administered business configuration with no environment-selected or
hard-coded customer, industry, persona, template, or sample-data fallback.

## What Happened

- The evaluation found reusable auth, messaging, knowledge, retrieval, and
  delivery infrastructure, but the active bot and console remain materially
  coupled to recruitment, VFIC, and LG Display. The codebase is not universal
  today.
- An eight-phase, test-first implementation plan was approved and red-team
  corrected. It introduces immutable database-backed installation revisions for
  one customer/industry per database and an allowlisted, code-owned capability
  registry.
- Persona was explicitly separated from runtime authority: it may control voice,
  tone, disclosure, and handoff policy, but cannot enable tools, repositories,
  capabilities, or live-data claims.
- The rollout distinguishes Release A, an isolated adoption-only artifact for
  the existing recruitment installation, from Release B, the first distributable
  universal image.
- Validation passed for the plan structure and cross-phase contracts. No
  application code, migration, prompt, webhook, or deployment change occurred.

## Reflection

Generic templates alone would create a false sense of universality because the
router, tools, authority sources, workers, and UI still encode recruitment
semantics. The safer boundary is a domain-neutral kernel whose database manifest
selects only compiled capabilities. The strongest red-team correction was to
treat configuration changes as delivery-authority changes, not merely cache
invalidation.

## Decisions Made

| Decision | Rationale | Impact |
|---|---|---|
| Use immutable database-backed installation revisions | Admins need auditable frontend configuration without customer-specific images | A clean install remains inactive until explicitly validated and activated |
| Keep capabilities code-owned and allowlisted | Database settings must not become executable plugins | Settings select supported behavior but cannot define tools, code, SQL, or import paths |
| Remove all business fallbacks | A missing configuration must never silently become VFIC/recruitment | Unconfigured deployments fail closed instead of answering in the wrong industry |
| Use monotonic `authority_generation` | Returning to an older manifest must not revive stale queued work | Activation, rollback, suspension, and active-KB changes create new delivery authority |
| Serialize dispatch against authority mutations | A final check alone cannot prevent activation from racing provider submission | Dispatch takes a shared PostgreSQL barrier; authority changes take its exclusive side |
| Make Release B the first universal image | Adoption compatibility and universal enforcement have different risk profiles | Release A stays isolated and cannot be distributed as the generic product |

## Next Steps

- Start with phase 1 characterization and mandatory PostgreSQL/browser test
  harnesses from the [implementation plan](../../plans/260715-0141-universal-industry-platform/plan.md).
- Use the [validation report](../../plans/260715-0141-universal-industry-platform/reports/validation-report.md)
  as the execution baseline; implementation remains pending.
- Obtain separate human approval before each hand-written migration set,
  protected bot behavior or webhook change, public-contract change, and any
  production deployment.
