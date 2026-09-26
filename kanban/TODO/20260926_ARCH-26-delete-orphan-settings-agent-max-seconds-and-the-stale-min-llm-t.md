---
id: ARCH-26
title: "Delete orphan Settings.agent_max_seconds and the stale min_llm_time_budget comment"
severity: low
area: architecture
labels: [dead-code, config-sprawl]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# ARCH-26 — Delete orphan Settings.agent_max_seconds and the stale min_llm_time_budget comment

**Severity:** low · **Area:** architecture · **Effort:** S · **Labels:** dead-code, config-sprawl

**Trạng thái:** TODO

## Problem

core/config.py keeps agent_max_seconds although its own docstring says the hard cap was retired and nothing enforces it; the only code reference is a test that sets it to 0.1s specifically to assert it has no effect — a characterization test of removed behavior. Immediately below, a dangling comment block still describes a min_llm_time_budget gating rule for a field that no longer exists anywhere in the repo. Operators reading Settings can believe an 8.5s agent cap is active when the agent is deliberately uncapped.

## Evidence

- backend/app/core/config.py:297-300 — 'Retired as a hard cap — the agent is no longer wrapped in asyncio.wait_for…' above agent_max_seconds: float = 8.5
- backend/app/core/config.py:351-353 — comment references min_llm_time_budget; repo-wide grep finds no such field or symbol
- backend/tests/test_graph_runner_turn.py:1242-1243 — monkeypatches agent_max_seconds=0.1 to pin that the dead knob has no enforcing effect
- docs/troubleshooting/chatbot-response-path.html:276 — ops docs still list agent_max_seconds 8.5 as a turn stage
- backend/app/core/config.py:276,309 — chat_turn_job_timeout comments cross-reference the retired knob

## Impact

A maintainer tuning turn latency can waste time on a knob that does nothing, or re-'fix' the test that guards nothing; the stale comment misdocuments the deadline model with a fallback mechanism that no longer exists.

## Suggested fix

Remove the agent_max_seconds field and both cross-reference comments (config.py:276, :297-300, :309), delete the orphaned :351-353 comment block, delete the monkeypatch pair at test_graph_runner_turn.py:1242-1243 (keep the surrounding test), and drop the table row in docs/troubleshooting/chatbot-response-path.html:276. pydantic-settings extra='ignore' means any leftover AGENT_MAX_SECONDS env var is silently ignored after removal. config.py is a protected path — needs owner approval.

## Notes

Related dormant-config cleanup: ARCH-27 removes the FAQ-bypass flag.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
