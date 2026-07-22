# Working-hours contradiction recovery

**Date**: 2026-07-22 23:15
**Severity**: High
**Component**: `backend/app/graph/router.py`, `backend/app/graph/clients.py`, `backend/app/graph/grounding.py`, `backend/app/services/recommendation/availability.py`
**Status**: Resolved

## What Happened

The chatbot had the correct LG evidence in retrieval, then threw it away and contradicted itself. A query like "giờ làm của LG" was not landing on the grounded FAQ-detail path, so the right hours never counted. Another authority override could replace a grounded reply outside `list_active_jobs`.

We also caught three pre-deploy blockers: shared-session prefetch was unsafe, `EXPLORE` was too eager to pull project catalogs, and entity grounding matched too loosely across similar projects.

## The Brutal Truth

This was maddening because the model had the right answer in hand and we still lost it. Retrieval said one thing, routing said another, and the override layer was ready to mistrust the result anyway. Bugs like this burn time because every layer looks plausible until you trace the whole path.

## Technical Details

- Working-hours phrases were added to the FAQ-detail router so LG shift questions now take the grounded `knowledge_lookup` path.
- Authority override now only runs when `list_active_jobs` was actually dispatched, so a non-authority turn cannot discard a valid reply just because the output happens to contain the active-job payload shape.
- FAQ-detail prefetch now uses isolated retrieval sessions when available; otherwise it falls back to sequential calls because the request-scoped `AsyncSession` is not concurrency-safe.
- `EXPLORE` stays RAG-only so turns do not load every project catalog.
- Entity grounding now canonicalizes exact slug/display identity, so `LG Display` can validate `lg-display` but unrelated projects cannot satisfy one another’s claims.
- Verification: the full backend suite passed with 2,058 tests and 23 expected skips;
  frontend lint, typecheck, 494 unit tests, and the production build also passed.

## What We Tried

- Fixed the routing gap first instead of papering over the contradiction downstream.
- Rejected broad string cleanup because it would have hidden the authority bug.
- Rejected concurrent prefetch against the shared session and added the isolated-session path plus sequential fallback.
- Replaced fuzzy entity matching with exact canonical identity checks to stop cross-project bleed-through.

## Root Cause Analysis

The root cause was two broken assumptions. Working-hours questions were not classified tightly enough, and the authority override treated a non-authority reply like a candidate for replacement. Once they lined up, a correct LG hours answer could be discarded even though retrieval was fine.

## Lessons Learned

- Routing and authority checks have to agree on what kind of turn this is.
- Shared async sessions are not a concurrency boundary; pretend otherwise and you get race-prone prefetch.
- EXPLORE must stay bounded or it stops being exploration and becomes silent overreach.
- Similar tokens are not the same entity. Exact canonical identity is cheaper than debugging a false positive later.

## Next Steps

- Keep the router and grounding regressions in place for the next chatbot cut.
- Watch for any new FAQ-detail path that can bypass the authority gate.
- Owner: chatbot graph maintainers. Timeline: already fixed, but the next turn that touches routing or grounding needs to preserve these constraints.
