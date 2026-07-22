---
date: 2026-07-22
session: single-page-vacancy-catalog
status: resolved
scope: recommendation-catalog-routing-and-single-page-project-visibility
---

# Journal: 2026-07-22 20:13 - Single-page vacancy catalog drift

## Context

A generic hiring query for the active Rorze one-page knowledge base was not
showing up in the vacancy catalog. The project had a ready direct file, but the
generic hiring path was still treating vacancy discovery as if it belonged only
to structured `Job` rows.

## What Happened

The generic hiring path omitted the active Rorze one-page knowledge base, even though the project had a ready direct file and explicit hiring content. The bot was still behaving like vacancy answers lived only in the `jobs` table, so a valid single-page project could disappear from a generic hiring query if there was no matching structured row.

## The Brutal Truth

This was a dumb authority split. We had the data, but not in the route the bot actually used. The catalog was narrow, routing had drifted, and the result was a clean-looking answer path that silently dropped the one project users cared about. That is exactly the kind of failure that feels cheap in code review and expensive in production.

## Technical Details

The fix changed two load-bearing paths:

- `RecommendationRepository.list_active_jobs()` now reads both structured `Job` rows and active `DIRECT_CONTEXT` projects, projects only when `index_card` exposes explicit `roles` or `key_roles`.
- Structured jobs and direct projects are de-duplicated by project id, then interleaved so one source cannot starve the other.
- `run_turn()` now treats `vacancy_listing` as a dedicated catalog route: it always uses `list_active_jobs(top_k=10)` and no longer lets EXPLORE/focused direct-context resolution hijack the vacancy lane.

Regression coverage now pins the behavior from three sides: the integration catalog test for an active single-page project, the repository tests for direct-project inclusion / empty-catalog / no-match behavior, and the graph runner test that proves generic vacancy listing bypasses focused single-page context.

## What We Tried

- Keeping the old job-only catalog. That preserved the bug.
- Letting routing decide between EXPLORE, focused direct context, and the vacancy lane. That created drift and made the generic query depend on the wrong authority.
- Pulling direct-project data into the catalog only after the structured jobs existed. That still left ready single-page projects invisible whenever the job table was empty.

## Root Cause Analysis

The root cause was a bad assumption: vacancy discovery was treated as a Job-only problem. Once routing split into EXPLORE and focused direct-context branches, the generic hiring query stopped having a single authoritative path. The code answered from whichever lane happened to win instead of from the actual catalog of current opportunities.

## Lessons Learned

If a product promise is "what is currently hiring," the code must define that catalog explicitly and fail closed around explicit roles. Do not let route heuristics decide whether a real opportunity exists. Also, direct-file projects are not discoverable unless their card data is explicit enough to survive projection. If `roles` are missing, they should stay invisible instead of being guessed.

## Next Steps

- Keep the catalog rule strict: only explicit roles, ready direct files, and deduped source mixing belong in vacancy answers.
- Treat future route changes that touch `vacancy_listing` as a review gate, because this bug came from routing drift, not from one broken function.
- Watch for new single-page projects that need `roles` or `key_roles` populated before they can be advertised through the generic hiring path.
