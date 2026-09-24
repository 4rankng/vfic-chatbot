---
id: ARCH-12
title: "`services/conversation/bot_path.py` (1118 LOC) carries five responsibilities"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: in_progress
column: TODO
opened: 2026-09-24
---

# ARCH-12 — `services/conversation/bot_path.py` (1118 LOC) carries five responsibilities

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

One file owns identity ensure, the inbound guards, the Redis lock lifecycle, the TOCTOU send claim, outcome recording, the reconcile sweeps and the proactive path. The lock family is pure Redis plus model-state logic with no dependency on the send path.

## Evidence

- `backend/app/services/conversation/bot_path.py:70,93,124-186` — identity ensure, creating `Contact` + `ContactChannelIdentity` + `Conversation` atomically.
- `backend/app/services/conversation/bot_path.py:187,195,207,258` — inbound guards (`semi_auto_inactive`, `run_start_guard`, `record_inbound`, `escalate_extracted_intent`).
- `backend/app/services/conversation/bot_path.py:329,365,392,417` — lock lifecycle; `:452,473` — the TOCTOU send claim.
- `backend/app/services/conversation/bot_path.py:560,770,997` — outcome recording; `:799,820` — reconcile sweeps; `:861,966` — proactive outcome and message preparation.

## Impact

Five unrelated change reasons share one file, and the module sits on the hot turn path (PERF-03, PERF-06), so a lock change is reviewed against the send path and vice versa.

## Suggested fix

Natural seam: `conversation/locking.py` (`:329-451`), `conversation/send_claim.py` (`:452-559`, `:997`), `conversation/bot_outcome.py` (`:560-798`) and `conversation/reconcile.py` (`:799-860`). The lock family is the cleanest cut in the codebase — pure Redis plus model-state logic, no dependency on the send path.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
