---
id: ARCH-05
title: "`graph/clients.py` (1626 LOC) holds seven responsibilities and duplicates `graph/grounding.py`"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# ARCH-05 — `graph/clients.py` (1626 LOC) holds seven responsibilities and duplicates `graph/grounding.py`

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** IN_PROGRESS

## Problem

One file carries LangChain reasoning-field compatibility, Redis LLM observability, prefetch heuristics, grounding/authority extraction, provider retry/quota/failover, the tool loop and the chat factories. The grounding concern is a second implementation of a module that already exists.

## Evidence

- `backend/app/graph/clients.py:35,49,85` — reasoning-field compatibility; `:139-141,142,158` — Redis LLM observability; `:176-219` — prefetch heuristics; `:254-277,422-443` — provider retry/quota/failover.
- `backend/app/graph/clients.py:283,314,363,387,406` — `_active_job_safe_reply`, `_ground_reply`, `_negative_job_authority`, `_matched_job_authority`, `_ground_active_job_reply`.
- `backend/app/graph/clients.py:663` — `MiniMaxAgent`; `:1410,1421` — `_chat_for_role`/`_minimax_chat` factories.
- `backend/app/graph/grounding.py:108,178` — hallucination stripping and `extract_surfaced_entities` already exist, so concern 4 is an accidental second grounding module rather than a new one.

## Impact

Every LLM call path crosses this file. Two owners for reply authority means a grounding change can be applied to one and not the other, and the file's size is why the graph import guard is worth so little here.

## Suggested fix

Natural seam: split concerns 1+2+3+5 into `graph/reasoning_compat.py`, `graph/llm_observability.py`, `graph/prefetch.py` and `graph/provider_failover.py`; move concern 4 (`clients.py:283-421`) into the existing `graph/grounding.py` so grounding has one owner; keep `MiniMaxAgent` + the factories in `clients.py`. Do not split `MiniMaxAgent` itself — its tool loop is cohesive.

## Notes

F5's grounding half is the same duplication pair as ARCH-17(f).

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
