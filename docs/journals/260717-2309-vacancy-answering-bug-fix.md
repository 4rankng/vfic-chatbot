---
date: 2026-07-17
session: vacancy-answering-bug-fix
---

# Journal: 2026-07-17 — Vacancy Answering Bug Fix

## Context

The published recruitment KB already contained the valid LG Display Tràng Duệ vacancy and salary data. The bug was not missing content; it was the wrong authority path. A later active-job-only route treated vacancy questions as if the live catalog were the only source of truth and fell back to catalog-unavailable even when the assigned KB had a direct answer.

## What Happened

We changed vacancy handling so authority follows the question. Generic requests for all current jobs use required `list_active_jobs`, while specific company, location, or role questions use `search_knowledge`. `run_turn()` can answer specific questions from assigned direct-context KB evidence before any LLM rewrite. Follow-up salary/detail questions combine the prior vacancy query with the current question so the thread stays scoped to the same company evidence.

The direct-context side also gained deterministic `Question:` / `Answer:` matching. When the KB has a canonical FAQ block that matches the user query, the runner returns that answer verbatim instead of letting the model rewrite vacancy or salary facts.

## Reflection

This was a self-inflicted authority bug. We had the right published data and still routed around it, which is exactly how you end up returning a useless “catalog-unavailable” reply for a question the KB can already answer. That is maddening because it wastes both the user’s time and ours.

## Decisions

- Generic “what is hiring?” questions use the complete structured ACTIVE Job catalog.
- Specific company, location, or role questions use the assigned published recruitment KB in both direct-context and RAG modes.
- Canonical FAQ direct-context matches must return verbatim answers; the model is not allowed to rewrite vacancy or salary facts.
- Vacancy follow-ups must combine the prior vacancy query with the current question so salary and benefits stay anchored to the same thread.
- `list_active_jobs` is authoritative for generic full-catalog listings, but it does not override a specific published recruitment-KB answer.

## Next

Keep the regression coverage pinned to the exact LG Display query, the salary follow-up, and the router/tool contract so we do not drift back into active-job-only thinking. Any future vacancy routing change needs to prove it still prefers published KB evidence before touching the fallback path.
