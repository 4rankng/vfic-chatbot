---
date: 2026-07-15
session: universal-platform-phase-one
status: phase-one-characterized
scope: baseline-contracts-and-fail-closed-harnesses
---

# Journal: 2026-07-15 — Universal platform phase one

## Context

Phase 1 establishes migration oracles for the proposed universal-industry
platform without changing production runtime behavior. The current codebase is
not universal: startup, routing, tools, knowledge fallbacks, extraction, and the
admin console still assume VFIC/LG Display recruitment. Business configuration
must ultimately be database-owned and frontend-administered rather than inferred
from source code, environment values, browser-local defaults, or sample data.

## What Happened

- Added explicit empty, recruitment, and product-advisory fixtures. They require
  customer identity, pack, capabilities, persona, template, and integrations;
  the empty fixture contains no business configuration or rows.
- Characterized current recruitment routing, template creation, knowledge
  fallbacks, configuration loading, route authority classes, and queue/outbox/
  provider boundaries. These assertions are migration oracles, not approved
  universal behavior.
- Confirmed that persona content can vary but has no authority. It may shape
  voice and policy, but cannot enable capabilities, tools, repositories, or
  live-data claims.
- Recorded the clean-migration exception: 17 legacy recruitment/manual-labour
  rows are seeded into `worker_feature_catalog` by existing migrations. No
  migration was changed in Phase 1.
- Added a mandatory PostgreSQL integration lane that uses matching loopback-only
  async/sync URLs, creates a uniquely prefixed database, migrates it to Alembic
  head with pgvector, rebinds FastAPI sessions, proves transaction rollback,
  blocks external sockets/HTTP, drops the database afterward, and fails rather
  than skips when infrastructure is unavailable.
- Replaced the retired browser provisioning path with a disposable Playwright
  harness. It accepts only loopback databases ending in `_e2e`, uses dedicated
  Redis database 15, requires ownership markers before reset/drop, scrubs live
  provider credentials, blocks external backend and browser traffic, runs the
  real FastAPI/Vite stack, and tears down its database after the run.
- Verification gates passed exactly: backend 1,126 passed with 20 legacy skips;
  integration 4 passed with 0 skipped; frontend lint, typecheck, and build passed,
  with 16 focused tests and 93 Claude-project tests; Playwright 4 passed with 0
  skipped.

## Reflection

The passing gates establish a trustworthy baseline, not universal readiness.
They make the current coupling measurable and give later phases fail-closed
proof, while preserving existing candidate-facing and production semantics.
The 17 migration-seeded catalog rows are especially important: an application
fixture can be empty even though a database migrated to head is not yet free of
business data.

## Decisions

| Decision | Rationale | Impact |
|---|---|---|
| Treat current recruitment assertions as migration oracles | Existing behavior must remain reproducible until each fallback is deliberately removed | Later phases must update the oracle only with approved semantic changes |
| Keep persona separate from authority | Editable prose cannot safely authorize code or claims | Capabilities and data authority remain allowlisted and code-owned |
| Make business configuration database-owned and frontend-administered | Browser defaults and environment inference cannot provide auditable installation state | Missing configuration must eventually fail closed |
| Require real isolated integration and browser lanes | Unit doubles cannot prove migrations, database binding, rollback, or network isolation | Selected lanes fail on missing infrastructure and never silently skip |

## Next

- The overall universal-platform plan is not complete; this entry records only
  the Phase 1 baseline and safety harnesses.
- Phase 2 must obtain explicit human approval before any hand-written migration
  or public-contract change, then introduce the database-backed installation
  revision boundary without weakening these gates.
- Preserve the fallback inventory and exact non-zero execution checks as later
  phases remove recruitment defaults and prove a genuinely empty installation.
