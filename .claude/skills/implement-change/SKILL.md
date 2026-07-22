---
name: implement-change
description: Implement a Ting Ting feature, fix, refactor, configuration change, or repository tooling change using the project workflow and approval gates.
---

# Implement a change

1. Read root `AGENTS.md`, identify the task surface, then load only the matching
   source-of-truth docs and 2–3 neighboring files. Use `TECH.md` when the system
   map or cross-module architecture is relevant. Check `plans/` for overlapping
   work and preserve unrelated edits.
2. State the expected artifacts, acceptance criteria, exclusions, constraints,
   touchpoints, and any approval-gated operation.
3. For broad or risky work, create a plan under `plans/<timestamp>-<slug>/` and
   obtain approval. For a bug, reproduce the failure and add a regression test.
4. Implement the smallest complete change using existing architecture and test
   patterns. Do not alter public contracts unless that scope was approved.
5. Invoke the `verify-change` skill. Broaden verification when shared behavior or
   contracts changed.
6. Review security, performance, accessibility, error handling, compatibility,
   and documentation impact before reporting completion.

Stop for approval whenever root `AGENTS.md` marks the operation as protected.
