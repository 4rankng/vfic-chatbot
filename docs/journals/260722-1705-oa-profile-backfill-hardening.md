---
title: OA profile backfill hardening
date: 2026-07-22
session: oa-profile-backfill-hardening
---

# OA profile backfill hardening

**Date**: 2026-07-22 17:05
**Severity**: High
**Component**: OA profile enrichment, backfill, and deploy maintenance
**Status**: Resolved

## What Happened

Production showed candidate profiles missing display names and avatars after OA enrichment. The broken part was not the provider alone. We had a stale-read/provider-await/write-overwrite race in the enrichment path, and the backfill runner was fragile: detached web execution, incomplete processing, and no durable checkpointing meant a sweep could stop halfway and leave the same bad state behind.

## The Brutal Truth

This was the kind of bug that wastes days because every piece looked “mostly fine” until they ran together under load. We let old snapshots win over newer writes, then pretended a best-effort background run was enough to clean it up. It wasn’t. The result was broken candidate identity data in prod and a maintenance path that could quietly quit before finishing the job.

## Technical Details

- The enrichment code now does fresh reads before deciding completion and uses atomic blank-only updates so it will not overwrite non-blank values that arrived after the provider call.
- The backfill runner pages eligible rows, retries each profile with bounded backoff, checkpoints against the database, and holds a PostgreSQL advisory lock so only one sweep can run at a time.
- A dedicated `oa-profile-backfill` container now runs after the active web color is healthy instead of piggybacking on a detached web exec.
- Exit codes are explicit: `0` for completion, `2` for incomplete work after a full run, and `3` when the advisory lock is already held.

## What We Tried

- We reproduced the overwrite risk by forcing stale contact data through the enrichment path and confirmed that provider data could still clobber newer blank/non-blank state.
- We switched the write path to blank-only atomic updates and re-read the row state after commit.
- We replaced the detached execution model with a dedicated maintenance service, JSON progress, and restart-safe pagination.

## Root Cause Analysis

The real failure was architectural: we treated enrichment as if a single read and a single write were enough. That assumption broke the moment concurrent updates, retries, and partial backfill runs entered the picture. The runner also had no hard boundary between “started” and “finished,” so an incomplete sweep could masquerade as progress.

## Lessons Learned

- Never write provider data back with a stale snapshot when concurrent user/admin edits are possible.
- Maintenance jobs need checkpoints, retries, and exit codes, not just “run this command in the background.”
- If rollback safety depends on a job stopping cleanly, make that boundary explicit in the container model.

## Next Steps

- Keep maintenance container and backfill guardrails as supported path for future OA profile repair runs.
- Keep the tests for blank-only updates, fresh reads, paging, retries, and advisory locking in place.
- Owner: backend maintainer on the next profile-enrichment change. Timeline: before the next production backfill, not after another partial sweep.
