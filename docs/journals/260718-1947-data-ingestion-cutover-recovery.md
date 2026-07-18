---
title: Data ingestion cutover recovery
date: 2026-07-18
session: data-ingestion-cutover-recovery
---

# Data ingestion cutover recovery

## Context

Phase 3 of the ingestion plan looked done after the focused tests passed, but the first pass was still wrong in the ways that matter: category projections could become live before an explicit Project cutover, and rollback did not truly restore the prior authority state. The plan had already converged on durable lease metadata, explicit cutover, and full-fidelity contact embedding, so the remaining work was about making those contracts real instead of merely green.

## What Happened

Adversarial review found the bad shape: category work was being prepared in a way that could leak active projections too early, and the rollback path was incomplete. We redesigned the flow around shadow preparation plus authority-gated coexisting projections, then made cutover idempotent and rollback restore the snapshot from `project.category_cutover_snapshot` instead of pretending category clear was reversible authority control.

The stale identity-map lease bug also showed up under retry pressure. We hardened the worker and service boundary around `processing_token`, `lease_expires_at`, and `attempt_count` so a dead or expired claim can be reclaimed safely without duplicating evidence. The test isolation leak was real too: the failure-injection test had to clean up its own session state instead of leaving debris behind for the next case.

## Reflection

The frustrating part is that the first implementation made the happy path look clean while hiding the dangerous behavior. That is exactly the kind of bug that burns time later because it passes the narrow test you wanted and fails the system you actually run. The sanitized full-fidelity contact handling was the right call, but it also made the tests more sensitive: we had to prove the provider-bound text kept full contact fields while logs, errors, and diagnostics stayed scrubbed.

## Decisions

- Keep category activation as shadow preparation until explicit Project-wide cutover.
- Store and restore authority from `category_cutover_snapshot`; do not fake rollback with a clear path.
- Keep lease recovery durable with `processing_token`, `lease_expires_at`, and bounded `attempt_count`.
- Preserve full contact fidelity for embedding, but keep diagnostic surfaces sanitized.
- Treat the migration as reversible and verify upgrade/downgrade, defaults, and retry behavior together.

## Next

The final verification run covered the new integration cases, the migration roundtrip, and the worker recovery path, and it still had the unrelated known graph test failure in the background. That is acceptable for now, but it should not be ignored forever.

Status: DONE
Summary: Phase 3 moved from a misleading green path to a correct cutover-and-rollback contract with durable lease recovery and sanitized full-fidelity contact embedding.
Concerns/Blockers: An unrelated known graph test failure remains outside this change.
