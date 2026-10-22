# 2026-10-22 — Bot trust post-mortem: posture truth, no repetition, escalation, honest identity

## Symptom (Zalo, user Toàn, 2026-10-21 19:06–19:29, unfollowed)

One real conversation exposed five trust failures at once:

1. The bot pitched **4P Electronics as seated work** while the plant stands its
   workers (its own posting pays a đứng-machine allowance), then contradicted
   itself across turns (ngồi → đứng → ngồi).
2. Every follow-up re-pasted the same job/salary blurb — long, repetitive,
   template-shaped.
3. The user disclosed **broken limbs**; the bot kept consulting on jobs instead
   of handing off to a human.
4. After the user gave his phone number, the bot kept interrogating
   (khu vực/lương/tiêu chí) — a form, not a consultant.
5. Asked whether it was a bot, it neither confirmed nor denied — a dodge that
   reads as a lie. The user unfollowed.

## What changed (four guard groups, `graph/trust_guards.py` is the new module)

**A — structured job attributes + hard pre-filter.** `jobs` gains
`posture` (`seated_only|standing_only|mixed|unknown`),
`heavy_lifting` (`no|light_under_5kg|heavy_over_10kg|unknown`) and `health_cert`
(`mandatory_candidate_pays|company_sponsored|none_initially|unknown`)
(Alembic 0078, backfilled from posting text with sources in the migration
note; 4P = `standing_only` per the standing-machine allowance). The matching
authority filters deterministically BEFORE the LLM sees candidates:
`rank_projects(work_posture="seated")` drops `standing_only` AND `unknown`
projects; `no_heavy_lifting=True` keeps only known lifting-free rows. The lane
detects the constraint in the user text and pins the tool args server-side
(`required_tool_arg_overrides` → `clients.dispatch_one` merges the floor into
whatever the model passed) — no prompt rule is load-bearing.

**B — anti-repetition + brevity.** Persona §3 and a new system-level rules
block (`context._BREVITY_AND_NO_REPEAT_RULES`, prompt revision 13) forbid
re-sending job/salary/policy text the candidate already read, cap turns at
2–4 sentences, and require direct answers without re-pasting rosters. A
deterministic post-generation guard (`reply_repeats_prior_block`: ≥80% shared
text or one ≥60-char verbatim block vs the previous bot reply) triggers exactly
one regeneration under a no-repeat instruction.

**C — escalation + STOP.** Injury/disability disclosures
(gãy tay/chân, khuyết tật, tai nạn, phẫu thuật, thương tật, bất lực, liệt…,
diacritic-insensitive) short-circuit the turn: the reply IS
`vfic_hotline_reply()` — the operator-approved verbatim handoff with the VFIC
toll-free number **1800 7228** (the existing single-source constant; the
stored-hotline mechanism on the TingTing OA is untouched). One reply, zero
questions, model never runs. The turn a phone number arrives carries
`POST_PHONE_STOP_INSTRUCTION`: confirm receipt, end the interrogation, no new
pitch, no closing question.

**D — identity honesty.** The «neither confirm nor deny» rule is deleted.
Asked directly («bot à / AI à / người thật à»), the bot says it is an automated
assistant with real HR staff calling back when needed — never claims to be
human, still never opens with a self-introduction. A deterministic identity
instruction reinforces the persona rule on the matching turn.

## Evidence

- `backend/tests/test_trust_postmortem.py` — 59 tests: seated filter excludes
  4P from the ranked set AND the tool payload, arg-floor merge, escalation
  keyword families + non-triggers + verbatim reply (contains `1800 7228`, no
  question), phone-handover detection, repetition detector + retry wiring,
  persona honesty assertions, four `_agent_turn` wiring tests.
- `tests/golden/dataset.yaml` — six `trust_postmortem` turns with five new
  assertion kinds (`escalates_to_human`, `stops_after_phone`, `identity_honest`,
  `no_standing_pitch`, `no_repetition`) implemented in `tests/golden/runner.py`.
- `scripts/smoke_trust_guards.py` → `plans/reports/261022-bot-trust-postmortem-smoke.md`
  — 3-turn transcript through the real pipeline (LLM transport stubbed).

## Notes for maintainers

- The `unknown` posture is deliberately excluded from seated matches: an
  unparsed posting is not a promise. Re-run the 0078 inference or fix the row
  to make a plant pitchable.
- The escalation reply is code-authored verbatim (operator template). Do not
  paraphrase it in the persona or add questions after it.
- `required_tool_arg_overrides` is a MERGE floor, unlike `required_tool_args`
  which REPLACES: the model's own location/company composition survives
  beside the pinned constraint keys.
