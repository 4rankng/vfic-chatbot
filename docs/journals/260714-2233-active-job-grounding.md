---
date: 2026-07-14
session: active-job-grounding
---

# Journal: 2026-07-14 — ACTIVE-job grounding

## Context

A candidate asking whether VFIC recruited CO2 welders received a fabricated
vacancy claim. Production evidence showed no matching active job or knowledge
base content. The original catalog-bound proposal would have tried to infer
role claims after generation, which is brittle and could treat FAQ/project
catalogue text as hiring evidence.

## What Happened

- Added a typed ACTIVE-job lookup with `matched`, `no_match`, and `unavailable`
  outcomes. It admits only `jobs` records with `status=ACTIVE` and a positive
  `vacancy_count`.
- Added a deterministic graph guard for explicit vacancy questions and factual
  follow-ups before the fast lane, FAQ bypass, and LLM. Responses are rendered
  only from matching job records; no match and lookup failure have distinct,
  safe replies.
- Tightened token matching for job/project recommendations, removed zero-score
  project suggestions, and versioned recommendation cache entries when jobs
  change.
- Added regression coverage for the reported welder question, follow-ups,
  unavailable lookup, short-role phrasing, and substring collisions.

## Reflection

The important correction was architectural, not linguistic: current hiring is
a database fact, so it must be decided before generation rather than guessed
from free-form Vietnamese. Separating `no_match` from `unavailable` avoids the
more harmful failure mode of turning a database outage into a false statement
that VFIC is not hiring.

## Decisions Made

| Decision | Rationale | Impact |
|---|---|---|
| ACTIVE jobs are the sole vacancy authority | Catalog and KB material can describe a project but cannot prove a live opening | The bot cannot confirm a role from retrieval alone |
| Run the guard before every answer lane | Fast FAQ paths and the LLM previously bypassed evidence checks | Vacancy questions no longer reach those paths |
| Use whole-token matching | Substrings could equate unrelated Vietnamese terms | Fewer accidental job or project matches |
| Preserve an explicit unavailable state | Failed lookup is not evidence of no vacancy | Candidate receives a retry-safe availability message |

## Next Steps

- Deploy only after normal human approval; no production data or schema was
  changed in this work.
- Monitor the `vacancy_lookup` timing/status fields after deployment and add
  legitimate job records when recruitment opens for new roles.
- Keep vacancy details in ACTIVE job records; do not expand project cards or
  FAQ entries into hiring authority.

