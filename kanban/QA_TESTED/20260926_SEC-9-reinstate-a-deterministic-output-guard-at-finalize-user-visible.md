---
id: SEC-9
title: "Reinstate a deterministic output guard at _finalize_user_visible_reply before candidate sends"
severity: medium
area: security
labels: [llm-safety, candidate-facing, progressive-send]
effort: M
status: decided-no-change
column: QA_TESTED
---

# SEC-9 — Reinstate a deterministic output guard at _finalize_user_visible_reply before candidate sends

**Severity:** medium · **Area:** security · **Effort:** M · **Labels:** llm-safety, candidate-facing, progressive-send

**Trạng thái:** DECIDED 2026-09-27 — risk accepted by the owner, no code change

## Owner decision — risk acceptance (2026-09-27)

**Verdict: accept the risk. Do not reinstate the deterministic output guard. No source change is made by this card.**

The owner, on being offered the reinstate-vs-accept choice for this decision card, chose to record risk acceptance rather than restore the removed answer-review layer. The reasoning that makes this an acceptable close rather than a deferral:

- The removal was deliberate and documentation-aligned (`8e90001` removed the answer-review layer and the LLM safety judge together, and the `runner.py` module docstring was updated to say so). Reinstating it would reverse a considered decision, not repair an accident.
- The residual defences are real and still active on the same path: `strip_think_reasoning` removes provider reasoning tags, and `ground_reply` (`graph/grounding.py`) cross-checks cited job ids and entity assertions against tool evidence before anything is sent. Those are the guards that stop a fabricated-claim class of failure, which is the highest-frequency one on this channel.
- Progressive send genuinely narrows the window, as the card's Problem section says. That risk is accepted knowingly rather than discovered later; the card is the record of that knowledge.
- Reinstating a blocklist + PII-mask + length-ceiling guard is not free: a term blocklist tuned against Vietnamese recruiting prose produces false positives on the exact candidate-facing copy that converts, and a PII mask that fires on job ids or salary figures degrades real answers. The remedy has a known cost to the primary business outcome, which is why this is genuinely the owner's call and not an engineer's.

**What this acceptance does NOT cover** — reopen this card if any of these become true:

1. A prompt-injection incident reaching candidates through KB content. That is the scenario the residual `ground_reply` check does not cover, and it would convert this from an accepted risk into a live defect.
2. Any change to `progressive_send`'s dispatch ordering relative to grounding.
3. A change in the blast radius of `_finalize_user_visible_reply` — for example, if it is ever moved off the single converged reply boundary, or a second ungrounded send path is added alongside it.
4. A change in who may set `progressive_send` (`graph/types.py` — currently an admin-managed flag). If that flag's blast radius widens, the widened window is unaccepted.

**No further action is owed on this card.** Re-decision trigger is item 1; the remaining items are standing review conditions.

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
