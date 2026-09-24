---
id: PERF-04
title: "Direct-context lane runs an uncached full-KB scan every turn and re-sends the whole KB as prompt"
severity: high
area: performance
labels: [performance]
effort: M
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# PERF-04 — Direct-context lane runs an uncached full-KB scan every turn and re-sends the whole KB as prompt

**Severity:** high · **Area:** performance · **Effort:** M · **Labels:** performance

**Trạng thái:** DEV_COMPLETED

## Problem

`_DirectContextAdapter.resolve()` executes an uncached, unlimited join over every active project and loads the `normalized_text` TEXT column for all of them, on every turn whose route is not `vacancy_listing`. The capacity guard then re-selects the same row and re-tokenises the full text, and the whole text is sent as the system prompt.

## Evidence

- `backend/app/graph/factories.py:120-135` — `_DirectContextAdapter.resolve()` joins Project/KnowledgeBase/KnowledgeBaseDirectFile, `WHERE Project.is_active`, `order_by(Project.name, Project.id)`, with no cache and no LIMIT; invoked from `backend/app/graph/runner.py:1392`.
- `backend/app/models/knowledge.py:209` — `KnowledgeBaseDirectFile.normalized_text` is TEXT, loaded for every active project into the ORM identity map for the life of the turn.
- `backend/app/services/knowledge_base_capacity.py:74-88` — `require_direct_context_ready` re-`SELECT`s the same DirectFile and re-runs `_estimate_tokens` over the full text.
- `backend/app/graph/direct_context.py:191-215` — `build_direct_system` embeds the whole text (docstring: never truncates the KB text), sent as the system prompt at `backend/app/graph/runner.py:527`.
- `backend/app/services/ingestion/limits.py:26` — `MAX_NORMALIZED_TEXT_BYTES = 10 MB`, while the capacity guard only fails above ~1 M tokens (`backend/app/services/knowledge_base_capacity.py:24-30`).

## Impact

One uncached full-table scan plus a full-text column load per turn, a duplicated file read and O(n) token count, and — for a DIRECT_CONTEXT KB — the entire KB re-sent as prompt tokens on every LLM call. Cost and latency scale linearly with KB size until the ~1 M-token guard trips: at `llm_cost_per_mtok_input=1.0` a KB near the ceiling is on the order of $0.10 per call [EST], and it is also the largest per-turn allocation on a 4 GB box.

## Suggested fix

Cache the matching projection (slug, name, aliases, knowledge mode) in Redis under the existing `NS_PREAMBLE` namespace — it changes only on project edits that already bump that version (`backend/app/services/knowledge/project_index_repository.py:53,85`) — and keep the `normalized_text` load for the focused project only, via `defer`/`load_only` or a second targeted query. Fold the capacity check into that single query and cache the computed `estimated_input_tokens` alongside the file checksum. The prompt-shape/size question is a prompt-policy change and needs the `AGENTS.md` approval gate — flag it rather than change it.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
