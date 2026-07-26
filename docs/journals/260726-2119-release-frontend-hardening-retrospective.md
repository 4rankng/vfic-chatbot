---
title: Release and frontend hardening learned the hard way
date: "2026-07-26 21:19"
severity: High
component: release gate, blue-green deploy, frontend hardening
status: Resolved
---

# Release and Frontend Hardening Learned the Hard Way

## Context

This was the `plans/260726-2019-release-and-frontend-hardening` pass. The real surface was bigger than it looked: release scripts, the backend gate, and frontend route/performance behavior changed together. The final focused coverage contract exceeded 80% in every metric across the three high-risk production modules it measures. No deployment or commit happened from this session; the work stayed local.

## What happened

The first smoke pass was too loose. `backend/scripts/smoke_turn.py` accepted a generic turn outcome as success, which meant the route could look healthy before we had actually proved persisted delivery. Rollback had the same flaw in reverse: `backend/scripts/bg_rollback.sh` could claim restoration before the public edge, worker counts, and queue health were verified. We fixed that by forcing explicit post-flip checks against public `/health`, container state, and queue readiness before the state files were trusted.

On the frontend, the Vitest coverage wiring was ignored when it sat in the wrong project scope, so the gate looked present but did not actually enforce the changed surface. We tried to rescue that with a helper-only coverage scope, but that was the wrong answer: it was too small to represent the production change. The final coverage target now points at the changed high-risk production modules instead of pretending the whole app is covered.

## Reflection

The annoying part is that we spent time proving the obvious only after the scripts had already been built around false confidence. Green smoke was not evidence. A rollback message was not evidence. A coverage config that did not apply was not evidence. That is all painful, but it is better to admit it than keep a fake success path in the release story.

## Decisions

We kept `backend/app/services/release_gate.py` fail-closed on missing golden results and made the correctness check self-contained. That was the right boundary: golden correctness can be enforced directly, while latency is honestly not evaluated in fresh CI. I would rather document that limitation than bury it behind a misleading pass.

## Next

Keep the new smoke, rollback, and release-gate checks as the only source of truth. If this regresses, start with `backend/scripts/smoke_turn.py`, `backend/scripts/bg_deploy.sh`, `backend/scripts/bg_rollback.sh`, and `frontend/vitest.config.ts`. Do not widen the coverage story unless CI can actually enforce it.
