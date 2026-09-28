---
id: OPS-30
title: "backend/app/graph carries ~64 ungated Pyright errors across 11 files (runner, lanes, proactive, clients, usage, tools/*): Optional-flow narrowing, DecisionTraceSummaryCode literal mismatches, object-typed iteration"
severity: low
area: backend
labels: [type-safety, static-analysis, graph, tech-debt]
effort: M
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-28
---

# OPS-30 — backend/app/graph carries ~64 ungated Pyright errors across 11 files

**Severity:** low · **Area:** backend · **Labels:** type-safety, static-analysis, graph, tech-debt

**Trạng thái:** DEV_COMPLETED — 2026-09-28: `backend/app/graph` is at 0 Pyright errors (was 52 live; the card's 64 was stale — parallel sessions had already cleared lanes/adapters). The `DecisionTraceSummaryCode` Literal in `schemas/bot_run.py` gained the four drifted members after triage (record_decision is an inert compatibility sink); `TurnRoute.reason` is now Literal-typed; zero ignores added. Scoped pyright lane (`uvx pyright app/graph`) and the fast migration-walk subset now gate `release-check`; `backend/pyrightconfig.json` binds the venv for every invocation.

## Problem

The bot's core package (`backend/app/graph/` — runner, lanes, proactive, clients)
fails static analysis, but nothing gates it: the repo's `release-check` type-checks
only the frontend. The bot ships with a red type baseline, so new regressions hide
among known failures in the exact module with the repo's worst bug-fix history
(`runner.py` — 22 bug fixes per the code-health index).

Representative clusters (full list reproducible with a Pyright probe of the package):

- `runner.py` (6): `record_decision(summary_code=...)` called with literals outside
  `DecisionTraceSummaryCode` (`recipient_unreachable`, `allowed`, `channel_not_allowed`);
  `decide_turn` accessed on `None`; `_ProgressiveStream | None` passed as non-optional.
- `proactive.py` (27): seven `TurnOutcome` returns actually return plain `dict`;
  repeated `Optional` member access/calls.
- `lanes.py` (11): `ConversationPort` protocol lacks `escalate_extracted_intent` that
  the code calls; `TurnDecisions | None` passed where non-optional expected.
- `clients.py` (5): `str | _ContinueTurn` returned as `str`; `.content` on `object`.
- `usage.py` (9): `int(...)` over `object`-typed values from untyped JSON.
- `tools/jobs.py`, `tools/income.py`, `income_contract.py`, `tools/tingting_identity.py`:
  iterating `object`/`Never`; `join` over a generator that can yield `None`.

## Impact

- The bot's highest-churn module has no type safety net; Pyright output is noise, so
  real type regressions land unnoticed (same failure mode as OPS-29 in `services/lead/`).
- `DecisionTraceSummaryCode` literal mismatches mean the decision-trace enum has
  drifted from what the runner actually records — the trace data consumers may hit
  unhandled codes.

## Suggested fix

1. Triage `DecisionTraceSummaryCode` first: add the missing codes
   (`recipient_unreachable`, `allowed`, `channel_not_allowed`,
   `progressive_stream_mismatch`) to the enum in `decisions.py`, or fix the callers —
   this is the only cluster with runtime-data implications.
2. Fix `lanes.py:157` by adding `escalate_extracted_intent` to the `ConversationPort`
   protocol (the runtime attribute exists; the protocol lags).
3. `proactive.py`: type the helpers' return values as `TurnOutcome` instead of dict
   literals (7 return sites share the same shape).
4. `usage.py`/`income_contract.py`: narrow the untyped-JSON reads once at the boundary
   (`cast`/validation) instead of at each `int()`/iteration site.
5. After the package reaches zero errors, consider adding a scoped pyright lane
   (`pyright app/graph`) to `make release-check` so the baseline stays green — mirror
   of the frontend `npm run typecheck` gate.

## Notes

- Found during the 2026-09-28 BOT-01 verification; pre-existing debt, no runtime
  incident attributed to it yet. The repo has no Python type gate today, which is why
  this grew silently — grouped here rather than fixed piecemeal in unrelated tasks.
- Related: OPS-29 (same debt class in `services/lead/`).

---

_Opened 2026-09-28 from the graph-package diagnostics probe. Diagnostic counts reproduce with Pyright against `backend/app/graph`._
