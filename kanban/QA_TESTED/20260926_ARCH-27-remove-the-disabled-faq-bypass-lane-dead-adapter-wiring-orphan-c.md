---
id: ARCH-27
title: "Remove the disabled FAQ-bypass lane: dead adapter wiring, orphan config flag, phantom dashboard taxonomy"
severity: low
area: architecture
labels: [dead-code, observability]
effort: M
status: done
column: QA_TESTED
opened: 2026-09-26
---

# ARCH-27 — Remove the disabled FAQ-bypass lane: dead adapter wiring, orphan config flag, phantom dashboard taxonomy

**Severity:** low · **Area:** architecture · **Effort:** M · **Labels:** dead-code, observability

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The FAQ-bypass lane was deliberately disabled — tests pin that even a confident hit cannot short-circuit the LLM — but the wiring, port, dashboard taxonomy and config flag were never cut over. build_deps still constructs _FaqBypassAdapter and threads the embedder into it on every turn; try_answer has zero production call sites; _resolve_lane only routes clarification/direct_context/agent; BotRun schemas and the performance dashboard still accept and project a faq_bypass lane/stage; and Settings keeps faq_fast_lane_enabled with a comment describing the removed zero-LLM template path. Anyone tracing why faq_bypass never fires must dig through test names to learn it is intentional.

## Evidence

- backend/app/graph/factories.py:385 — build_deps still constructs `_FaqBypassAdapter(db, clients.embedder, ...)` into GraphDeps on every turn
- backend/app/graph/adapters.py:334-362 — _FaqBypassAdapter.try_answer is the only production definition; no call site of try_answer or deps.faq_bypass outside tests
- backend/app/graph/runner.py:1015-1055 — _resolve_lane selects only project_clarification → direct_context → agent; 'bypass' does not appear in runner.py
- backend/tests/test_graph_runner_turn.py:1394-1396 — test_faq_bypass_hit_cannot_short_circuit_llm pins that the disable is deliberate
- backend/app/schemas/bot_run.py:54-55,120-123 and backend/app/reporting/infrastructure/performance_dashboard.py:59-60,508-509 — faq_bypass remains a valid lane/stage value that can no longer occur
- backend/app/core/config.py:340-344 — faq_fast_lane_enabled: bool = True with a comment describing the removed template fast lane; grep finds no reader anywhere

## Impact

An embedder argument is threaded through build_deps for a lane that cannot fire; dashboards advertise a phantom lane so operators tuning from stage_timings chase a structurally unreachable path; a dead Settings flag lets an operator set FAQ_FAST_LANE_ENABLED=false expecting behavior change and get nothing.

## Suggested fix

Complete the cutover: delete _FaqBypassAdapter, GraphDeps.faq_bypass + FaqBypassPort/FaqBypassResult, the factories.py:385 wiring, the faq_bypass entries in schemas/bot_run.py and performance_dashboard.py, the faq_fast_lane_enabled flag and its comment, and the removal-pinning tests — after verifying services/retrieval/faq_bypass.py has no other consumer (the deterministic cascade may be reused elsewhere). If the seam is being kept for a planned re-enable, instead document the intentional disable at types.py:133 and stop constructing the adapter per turn. Bot tool/prompt definitions are approval-gated — get the owner call on delete-vs-document first.

## Notes

Merged from two lanes (backend perf + docs hygiene), which found the wiring and the flag independently. The related faq_bypass_rule_terms migration 0026 is a different mechanism and stays.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
