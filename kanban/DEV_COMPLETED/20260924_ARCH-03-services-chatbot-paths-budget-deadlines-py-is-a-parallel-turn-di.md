---
id: ARCH-03
title: "`services/chatbot/{paths,budget,deadlines}.py` is a parallel turn-dispatch implementation that never runs"
severity: high
area: architecture
labels: [tech-debt]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# ARCH-03 — `services/chatbot/{paths,budget,deadlines}.py` is a parallel turn-dispatch implementation that never runs

**Severity:** high · **Area:** architecture · **Effort:** S · **Labels:** tech-debt

**Trạng thái:** IN_PROGRESS

## Problem

A second, test-only turn dispatcher sits beside `graph/runner.py`'s inline branching, and the retrieval time-boxing it describes is unwired: `match_documents(..., deadline=None)` is never passed a deadline in production, so the budget settings it reads are inert.

## Evidence

- `backend/app/services/chatbot/paths.py:11-13` — its own docstring: "Today the runner.py inline branching handles fast_lane / faq_bypass / agent; this module formalizes that into named paths so the dispatch is testable in isolation."; only caller `backend/tests/test_budget_and_paths.py:10`.
- `backend/app/services/chatbot/budget.py` — `TurnBudget`/`CallKind` per-turn caps, imported only by the dead `paths.py:21`.
- `backend/app/services/chatbot/deadlines.py:78-79` — `TurnDeadline.from_state` reads `turn_retrieval_budget_seconds`/`turn_rerank_budget_seconds` (`backend/app/core/config.py:266-267`); only caller `backend/tests/test_turn_deadlines.py:23`.
- `backend/app/services/retrieval/repository.py:324` — `match_documents(..., deadline=None)`; neither `backend/app/graph/tools/knowledge.py:268` nor `backend/app/services/job_service.py:81` supplies it.

## Impact

The retrieval time-boxing described at `deadlines.py:37-42` as an active protection does not exist in production: a slow vector arm can consume the whole turn budget and only the RQ-level deadline survives. This is the one finding in the audit with a plausible user-visible failure mode, not just maintenance cost.

## Suggested fix

Two options. (a) Delete `paths.py` + `budget.py` + `deadlines.py` and the two config keys, then document that turn time-boxing is deadline-at-epoch only; or (b) construct `TurnDeadline.from_state(state, settings)` in `backend/app/graph/runner.py` and thread it through `GraphRetrievalPort.match_documents`. The report recommends (a) — delete. Do not keep the module and the unwired call site both.

## Notes

This is the ticket that covers perf finding 16's time-boxing item (the unwired `deadline` parameter), per PERF-08.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
