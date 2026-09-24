---
id: ARCH-04
title: "`graph/fast_lane.py` and the `template` route strategy are unreachable, so every pleasantry costs a full LLM turn"
severity: high
area: architecture
labels: [tech-debt, performance]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# ARCH-04 — `graph/fast_lane.py` and the `template` route strategy are unreachable, so every pleasantry costs a full LLM turn

**Severity:** high · **Area:** architecture · **Effort:** S · **Labels:** tech-debt, performance

**Trạng thái:** TODO

## Problem

The router still emits a `template` strategy for pleasantries, but nothing consumes it — `runner.py` states outright that every normal user message reaches the LLM. The templates and the pleasantry classification are therefore write-only residue that advertises a lane which cannot fire.

## Evidence

- `backend/app/graph/fast_lane.py:56` — `template_for` is imported only by `backend/tests/test_golden_set.py:25`, `backend/tests/test_graph_decisions.py:24` and `backend/tests/test_persona_voice.py:24`.
- `backend/app/graph/router.py:87-93` — still emits `TurnRoute("small_talk", "template", reason="fast_lane_match", ...)`; `backend/app/graph/runner.py:355-357` only copies `route.strategy` into timings.
- `backend/app/graph/runner.py:1414-1416` — "Final replies do not use a template fast lane: every normal user message reaches the LLM."
- `backend/app/graph/ports.py:90` — `TurnDecisions.pleasantry_kind`, populated at `backend/app/graph/decisions.py:281-285` and never read in production.
- `backend/app/graph/router.py:29,43` (`TurnStrategy`, `FAST_MODEL_STRATEGIES`) and `backend/app/schemas/bot_run.py:40` (`fast_lane_match`) all still advertise the lane.

## Impact

A pleasantry costs a full LLM turn even though `fast_lane.py`'s templates exist and are voice-guarded by tests, and the `template` literal plus the `fast_lane_match` trace value mislead anyone reasoning about latency from `decision_trace`.

## Suggested fix

Two options. (a) Re-enable it in `_agent_turn` with a `route.strategy == "template"` early return calling `template_for(decisions.pleasantry_kind)`, which removes one LLM call from every greeting; or (b) delete `fast_lane.py`, the `template` strategy and `pleasantry_kind`. The report presents both and does not state a preference, but it records the disable at `runner.py:1414-1416` as a deliberate product decision and the residue as accidental, so (b) is the consistent choice. If the lane is kept, `FAST_MODEL_STRATEGIES` must drop `"template"` since a template route never reaches a model.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
