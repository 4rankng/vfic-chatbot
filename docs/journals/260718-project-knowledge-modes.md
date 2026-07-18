---
date: 2026-07-18
session: project-knowledge-modes
---

# Journal: Project-Owned Exclusive Single-page/RAG

## Context

This implementation split Project knowledge into two exclusive modes: a single-page direct-context mode and a twelve-category RAG mode. The ugly part is that this was not just a schema tweak; it changed authority boundaries, routing, admin behavior, and how the bot decides what evidence can actually answer a question.

## What Happened

The backend, frontend, and shared contracts were updated together so Projects now carry an explicit knowledge mode, category YAML contracts, scoped retrieval, and read-only derived projections. The runtime now forces project-aware tool scope, and the answer path still stays LLM-generated with scoped evidence rather than turning into a deterministic renderer for every factual turn.

Local verification passed. The final backend suite completed with 1552 passed and 19 skipped; frontend vitest completed with 353 passed, and Ruff/typecheck/lint/build were all green. The LG Display legacy migration was prepared and dry-run verified with the 0047→0048 roundtrip, but it was not deployed to production.

## Reflection

This was a large, mostly mechanical refactor, but the real risk was not the volume of code. It was getting the authority model wrong and silently reintroducing the same class of leakage or false certainty under a new UI. The frustrating part is that the code can “work” and still be wrong if the runtime gates are loose.

## Decisions

- Jobs YAML is the authority for job presence; the admin APIs now treat jobs as read-only projections.
- Final factual answers remain LLM-generated, but only with scoped evidence from the focused Project.
- Single-page Projects stay direct-context and never enter RAG chunking or category ingestion.
- RAG Projects use the twelve fixed categories, with clear replace/clear semantics instead of ad hoc edits.
- The LG migration stays additive and prepared only; production cutover still requires approved deployment, fresh backup, and production-shape validation.

## Next

Keep the production gates closed until the deployment workflow is approved and the migration is exercised on a production copy. The remaining work is not code completion; it is proving cutover safety and performance under real load before letting this replace the old knowledge path.
