---
id: ARCH-21
title: "Extract MiniMaxAgent.agent: 719-line method inside 1481-LOC graph/clients.py"
severity: high
area: architecture
labels: [god-module, chat-hot-path]
effort: L
status: todo
column: TODO
opened: 2026-09-26
---

# ARCH-21 — Extract MiniMaxAgent.agent: 719-line method inside 1481-LOC graph/clients.py

**Severity:** high · **Area:** architecture · **Effort:** L · **Labels:** god-module, chat-hot-path

**Trạng thái:** TODO

## Problem

graph/clients.py mixes four concerns: embedding clients, cut-answer text surgery, the MiniMaxAgent generation loop, and provider chat-model constructors. The core defect is MiniMaxAgent.agent, a single ~719-line method that inlines route prefetch, tool binding, tool dispatch, retry/failover, streaming, metrics, and answer finalization. Every provider-behavior change edits it.

## Evidence

- backend/app/graph/clients.py:291 — class MiniMaxAgent; agent() starts at :322 and the next method direct() starts at :1042, making agent ≈719 lines (file total 1481)
- backend/app/graph/clients.py:60 — GeminiEmbedder (:60), OpenRouterEmbedder (:112), build_embedder (:177) — embedding transport lives in the same module as the generation loop
- backend/app/graph/clients.py:226 — cut-answer surgery helpers _answer_was_cut/_should_continue_cut_answer/_join_answer_parts/_seam_remainder/_drop_dangling_tail (:226-289)
- backend/app/graph/clients.py:1174 — provider chat constructors _minimax_chat (:1174), _custom_chat (:1233), _openrouter_chat (:1285), _active_llm_provider (:1336), _chat_for_role (:1370)
- backend/app/graph/runner.py:362 — runner._agent_turn must pass 10+ kwargs (required_tool, required_tool_args, on_delta, on_evidence, resolved_tool_registry, …) into this one method, evidence of the collapsed abstraction

## Impact

The tool-loop invariants (prefetch vs required_tool guards, empty-retry, answer continuation, failover binding) are unverifiable by inspection; a misplaced edit to one concern silently changes turn behavior for every lane, and the module cannot be tested without stubbing all four concerns at once.

## Suggested fix

Move embedders + build_embedder to graph/embedders.py, the cut-answer helpers to graph/answer_repair.py, and the _*_chat/_chat_for_role constructors to graph/providers.py (tests monkeypatch these constructors — keep the module path stable or update patch targets in one commit). Then decompose MiniMaxAgent.agent into private phases on the existing local state (prefetch_routes(), _run_generation_round(), _finalize_answer()), keeping agent as a thin orchestrator so ports and tests keep their contract.

## Notes

REL-12/REL-15 edit inside agent() — sequence with this split. Companion to ARCH-20; both are the two files >1000 LOC in backend/app.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
