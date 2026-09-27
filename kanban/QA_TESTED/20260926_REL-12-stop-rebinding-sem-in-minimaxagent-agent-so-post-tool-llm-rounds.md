---
id: REL-12
title: "Stop rebinding sem in MiniMaxAgent.agent so post-tool LLM rounds keep the Redis concurrency cap"
severity: high
area: reliability
labels: [reliability, concurrency, telemetry]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-26
---

# REL-12 — Stop rebinding sem in MiniMaxAgent.agent so post-tool LLM rounds keep the Redis concurrency cap

**Severity:** high · **Area:** reliability · **Effort:** S · **Labels:** reliability, concurrency, telemetry

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

In `MiniMaxAgent.agent`, the local `sem` starts as the cross-process Redis LLM semaphore but is rebound to a fresh in-process `asyncio.Semaphore(parallel_tool_max_concurrency)` inside the multi-tool dispatch branch. Every subsequent loop iteration acquires the throwaway per-round semaphore instead of the Redis one, so any LLM round after a parallel tool round runs outside the deployment-wide concurrency limit and can never fail fast with LLMThrottled. The system prompt explicitly instructs the model to issue all independent tool calls in one round, so the rebind path is common.

## Evidence

- backend/app/graph/clients.py:354 — `sem = get_llm_semaphore()` at agent() entry (RedisLlmSemaphore)
- backend/app/graph/clients.py:712 — `async with sem:` guards each model call inside the tool loop
- backend/app/graph/clients.py:954-958 — `sem = asyncio.Semaphore(get_settings().parallel_tool_max_concurrency)` rebinds the same local for `_bounded` tool dispatch
- backend/app/core/config.py:363-364 — `llm_concurrency_limit: int = 8` ('max concurrent LLM calls, deployment-wide') with 1.5 s LLMThrottled fail-fast; :376 — `parallel_tool_max_concurrency: int = 4` (an in-process DB-pool guard)
- backend/app/graph/context.py:22-33 — _RUNTIME_RETRIEVAL_RULES instructs 'GỌI TOOL SONG SONG … gọi TẤT CẢ trong cùng một lượt', so multi-tool rounds are encouraged on every agent turn
- backend/app/graph/llm_semaphore.py:14-19 — the Redis semaphore exists precisely because each RQ job gets a fresh event loop

## Impact

After any multi-tool round, later rounds of the same turn bypass the 8-token deployment-wide LLM protection (extra 429s under load), lose the fail-fast that converts saturation into a clean suppressed turn (they can hang until the 60 s RQ job timeout), and `llm_queue_ms`/`llm_model_ms` record tool-semaphore waits (~always 0) — the queue-vs-model latency split goes blind exactly on tool-heavy turns.

## Suggested fix

Rename the tool-dispatch semaphore (e.g. `tool_sem` at :954) and use it only inside `_bounded`; inside the loop, replace the bare `async with sem:` at :712 with `async with get_llm_semaphore():` so every round reacquires the Redis semaphore.

## Notes

The faq_detail prefetch path already uses a separate name (`sem_pf`, clients.py:535) — the collision is only with the dispatch semaphore.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
