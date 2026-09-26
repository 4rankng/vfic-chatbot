---
id: SEC-9
title: "Reinstate a deterministic output guard at _finalize_user_visible_reply before candidate sends"
severity: medium
area: security
labels: [llm-safety, candidate-facing, progressive-send]
effort: M
status: todo
column: TODO
opened: 2026-09-26
---

# SEC-9 — Reinstate a deterministic output guard at _finalize_user_visible_reply before candidate sends

**Severity:** medium · **Area:** security · **Effort:** M · **Labels:** llm-safety, candidate-facing, progressive-send

**Trạng thái:** TODO

## Problem

The post-generation content boundary that used to sit between the model and the candidate was removed outright: runner.py:13-17 documents that the answer-review layer (regex cleaning, truncation, empty-reply verdicts, safety_verdict trace) and the LLM safety judge are gone. What remains is strip_think_reasoning (provider reasoning tags only) plus ground_reply, which validates solely that cited job ids and entity assertions match tool evidence; all other content passes through unchanged. The window widened this week: the progressive path dispatches the first bubble mid-generation, before any later review could exist.

## Evidence

- backend/app/graph/runner.py:13-17 — module docstring states the former answer-review layer and LLM safety judge were removed outright between generation and send
- backend/app/graph/runner.py:694-706 — _finalize_user_visible_reply, the converged reply boundary, returns strip_think_reasoning(raw) and nothing else
- backend/app/graph/runner.py:1408-1412 — the progressive first bubble is exactly ground_reply(visible_bubble, stream.evidence) wrapped in _finalize_user_visible_reply, then sent
- backend/app/graph/grounding.py:392-427 — ground_reply only cross-checks cited job ids and entity assertions; all other content passes through untouched
- backend/app/graph/runner.py:2061-2066 — the finalize comment still claims 'Generated replies receive the full safety policy' — stale after the removal
- backend/app/graph/types.py:161-167 — progressive_send is an admin-managed flag; when on, the first bubble reaches the candidate mid-generation

## Impact

A prompt-injected candidate message or a derailing model completion reaches candidates verbatim on a live revenue channel: offensive or off-policy text, staff phone numbers/emails echoed from KB content, or competitor solicitation pass with no filter. Recruiters cannot intervene in BOT-mode conversations, so nothing catches it before the candidate reads it.

## Suggested fix

Decision card — the removal looks deliberate (doc-aligned in 8e90001), so the first step is an explicit owner risk-acceptance or reinstate decision. If reinstating: a cheap deterministic guard inside _finalize_user_visible_reply (Vietnamese/English blocklist term scan, PII regex mask for VN phone/email/long digit runs, hard length ceiling — all non-model), verdict recorded in the decision trace (reuse the retired safety_verdict vocabulary, app/schemas/bot_run.py:137-139), one unit test per guard. Note: touching bot safety behavior is approval-gated per AGENTS.md.

## Notes

Materially new since wave 1: progressive streaming shipped 2026-09-26 (315c4fc, 531901c, 684bd3e, 38ad9d6). Deliberately severity medium pending the owner decision rather than presuming the removal was a mistake.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
