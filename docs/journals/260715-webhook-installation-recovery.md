---
date: 2026-07-15
session: webhook-installation-recovery
---

# Journal: 2026-07-15 — Restore legacy webhook processing while installation is inactive

## Context

The installation lifecycle is intentionally not activation-ready: the available
industry packs remain marked `runtime_ready=False`. A webhook early return had
made that unfinished lifecycle block all candidate messages before the existing
legacy bot path could run.

## Decision

When no active installation authority exists, Zalo Bot Platform and Official
Account webhooks now call the established handler without a runtime stamp. The
handler and worker already support this legacy form. An active installation
continues to stamp messages and uses the authority-aware path.

## Constraints

This is an incident-recovery compatibility path, not installation activation.
It does not seed installation records, change pack readiness, alter signature
verification, or weaken stale-authority suppression for stamped work.

## Verification

- Bot and OA unconfigured-webhook regression tests verify that the handler is
  called with no runtime authority.
- Existing authority-stamping and stale-authority tests continue to pass.
