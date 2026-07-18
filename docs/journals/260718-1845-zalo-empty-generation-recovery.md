---
title: Zalo empty-generation recovery
date: 2026-07-18
---

# Zalo empty-generation recovery

## Context

The photographed refusal came from the graph safety fallback, not from a Zalo transport-specific branch. Bot and OA share the same reactive graph, but they still differ by identity, history, and project focus, so parity must be checked at the conversation state level rather than by adapter label alone.

## What happened

The first implementation tried to recover empty generations in the runner, but that shape was rejected because it risked repeating tool loops and changing the wrong boundary. The final design moved recovery to the reactive agent call, kept it tool-free, and allowed exactly one extra attempt only when the first cleaned result was empty and retryable.

## Reflection

The production sub-trigger is still unproven from historical telemetry, so the fix is best described as resilience hardening for the observed failure mode rather than a forensic reconstruction of one exact turn. Focused verification was enough to prove the retry path, but the broader backend suite still showed unrelated concurrent failures in the worktree, so the final claim should stay scoped to the touched graph modules.

## Decisions

- Keep the retry boundary in the reactive agent path.
- Do not retry unsafe cleaned-empty replies.
- Do not repeat retrieval or tool dispatch on the retry.
- Preserve the existing deterministic fallback for persistent empties.
- Treat Bot/OA divergence as shared-graph, separate-state behavior.

## Next

- Monitor whether production telemetry needs a dedicated safety-trigger field later.
- Leave the unrelated suite failures to their owning work and avoid conflating them with this fix.
- No deploy was performed.
