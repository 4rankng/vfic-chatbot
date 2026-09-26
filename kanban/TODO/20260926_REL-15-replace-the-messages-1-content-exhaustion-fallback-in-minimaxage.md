---
id: REL-15
title: "Replace the messages[-1].content exhaustion fallback in MiniMaxAgent.agent with an unavailable reply"
severity: low
area: reliability
labels: [correctness, agent-loop]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# REL-15 — Replace the messages[-1].content exhaustion fallback in MiniMaxAgent.agent with an unavailable reply

**Severity:** low · **Area:** reliability · **Effort:** S · **Labels:** correctness, agent-loop

**Trạng thái:** TODO

## Problem

If the tool loop exhausts `max_iters` without ever producing a text round (a model stuck re-requesting tools), `answer_parts` is empty and the tail falls back to `messages[-1].content` — which after a tool round is the raw ToolMessage payload (an ACTIVE_JOB_LOOKUP_JSON dump or KB chunk). ground_reply passes it through because any job IDs in tool output are by definition in the surfaced set, so the raw tool text ships to the candidate.

## Evidence

- backend/app/graph/clients.py:1040-1053 — `if answer_parts: … else: final = messages[-1].content …` then `return _ground_reply(final, tool_results, …)`
- backend/app/graph/grounding.py:403-437 — ground_reply returns the reply unchanged when cited IDs are all in the surfaced set, so tool-output text passes validation
- backend/app/graph/clients.py:338 — max_iters defaults to settings.max_llm_calls_per_turn (6, config.py:366-368), all spendable on tool rounds

## Impact

Rare but candidate-visible: a raw JSON/KB dump delivered as the bot's answer; it also pollutes the decision trace with a 'final' round that is actually tool output.

## Suggested fix

In the `else` branch at clients.py:1046, return the lane's neutral unavailable text (e.g. VACANCY_LOOKUP_UNAVAILABLE_REPLY for vacancy turns, otherwise a generic Vietnamese 'chưa thể kiểm tra' line) instead of messages[-1].content, and record a degradation_reason on the trace.

## Notes

Adjacent to the 37b7cf54 completion work; the continuation path itself is well tested (tests/test_answer_completion_guard.py).

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
