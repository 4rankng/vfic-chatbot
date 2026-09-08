---
type: system
title: Safety filter chain and turn routing
description: Deterministic fast safety filter, LLM safety judge, retry-rewrite cap, grounding cross-check, pre-send claim fence, and the routing intents that drive model tier selection.
tags: [safety, fast-filter, llm-judge, grounding, retry, routing, fast-lane, model-tier]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
sources:
  - id: openwiki-source-3b192284fa645018ff2cdd55
    resource: repo://backend/app/graph/fast_lane.py
  - id: openwiki-source-a89af3f6f98ea26a1605ee61
    resource: repo://backend/app/graph/grounding.py
  - id: openwiki-source-5ec1084a2c96be1f336d86a1
    resource: repo://backend/app/graph/router.py
  - id: openwiki-source-6201c1a523eb3beb2c1d8be9
    resource: repo://backend/app/graph/runner.py
  - id: openwiki-source-66bf7d038f006b04f232f780
    resource: repo://backend/app/graph/safety.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

The pipeline's safety story is **fail-closed**: every reply must clear a
deterministic filter, optionally escalate to a slower LLM judge, retry at
most once on a rewrite, then pass a grounding cross-check and a
server-side claim fence before a single byte is sent. Routing sits ahead
of all of that so a greeting never spends 10 s on the LLM judge, and a
job-detail answer never gets away with an unsupported claim.

## Pipeline order (recap)

```text
agent → fast_safety_filter → needs_llm_safety?
        no  → combine_for_presend → pre_send_guard → send_message
        yes → llm_safety_check   → safe_to_send?
                yes → combine_for_presend → pre_send_guard → send_message
                no  → retry_rewrite? (attempt<1) → agent | combine_for_presend
                                    (final fallback: retry_exhausted_fallback)
combine_for_presend → grounding cross-check (validate_grounding) → pre_send_guard
```

The pre_send_guard is the last gate before the wire and is the only gate
that closes the crash-window and the recheck→send TOCTOU.

## Fast safety filter (deterministic, cheap)

`backend/app/graph/safety.py:fast_safety_filter` runs before every LLM
safety call. It is pure and runs in microseconds.

| Step | What it does |
|---|---|
| `strip_think_reasoning` | Removes `<think>…</think>` blocks (MiniMax M2 reasoning models) and discards any text after an unmatched `<think` opener so a truncated response never leaks deliberation. |
| Strip code fences, `<\/?minimax:…>` tags, Markdown bold/headings/hr | Cosmetic cleanup so the LLM safety judge sees the cleaned reply, not the wire format. |
| Collapse whitespace | Single spaces; max two newlines. |
| Compute `empty_after_clean`, `too_long_for_chat` (>1800 chars) | Decide the deterministic path. |
| `_RISK_RE.search(cleaned)` | Detect structural leakage: code fences, `<\/?minimax:`, JSON-shape leakage (`"safe_to_send"`, `"final_answer"`), tagged Vietnamese phrases (`logic nội bộ`, `tên node`, `biến hệ thống`, `hướng dẫn hệ thống`, `lời nhắc hệ thống`). |
| `blocklist_hit(output)` | High-precision lexical blocklist (English + Vietnamese prompt-injection patterns, vulgarity, self-harm). Hit → immediate fallback, skip the LLM judge. |
| Decision | `needs_llm_safety = empty_after_clean or too_long_for_chat or _RISK_RE.search(cleaned)`. The LLM judge is **only** consulted when this flag is set; every other reply flows straight to grounding + pre-send. |

`FALLBACK_REPLY` is a short Vietnamese redirect to VFIC's actual scope
("Tôi chưa thể xác minh câu trả lời này. Bạn đang quan tâm vị trí tuyển
dụng, mức lương, xe đưa đón hay hồ sơ ứng tuyển để tôi kiểm tra đúng
thông tin nhé?"). `retry_exhausted_fallback` selects `TECHNICAL_FALLBACK`
when the user's message matches the off-domain technical regex (code,
debug), otherwise the generic fallback.

### Truncation

`truncate_for_chat(text, limit=1800)` cuts at the last space within the
limit so an over-long reply stays bounded even when the LLM judge is
disabled (Slice E.4 fallback). An ellipsis is appended so the truncation
is visible to the user.

## LLM safety judge (escalation, 10s+)

Only when `needs_llm_safety` is set does the runner consult the LLM
judge (`MiniMax safety model`, configured via
`Settings.minimax_safety_model` or the OpenRouter safety model). The
judge returns a verdict; a "safe_to_send" verdict flows to
`combine_for_presend`, an "unsafe" verdict triggers **at most one
retry/rewrite** of the agent node (`attempt < 1`).

After the rewrite, the candidate passes through `fast_safety_filter`
again. If the result still fails the deterministic filter or the LLM
judge still flags it, the runner replaces the candidate with
`retry_exhausted_fallback(user_text)` and proceeds. The user always gets
a deterministic Vietnamese redirect, never a leaked failure mode.

## Grounding cross-check (sanitize-only)

`backend/app/graph/grounding.py:validate_grounding` runs against the
candidate just before `combine_for_presend` (or as part of the policy
finalize in `DeterministicReplyPolicy`). It is pure (no DB, no LLM) so
its branches are pinned by `backend/tests/test_grounding.py`.

- **Job-ID path.** `extract_cited_job_ids(reply)` pulls every UUID in
  `id=<uuid>` or bare form; `validate_grounding` diffs against
  `surfaced_ids` (the IDs the agent actually saw in tool results).
  Hallucinated IDs (`cited - surfaced_ids`) are **stripped** from the
  reply, not the whole reply replaced — the agent may still have useful
  non-citation content. The candidate is replaced only when the reply is
  entirely about a hallucinated job (no grounded content remains).
- **Entity path.** `validate_entity_grounding` pulls
  company/factory/project names from the structured tool payloads
  (`ACTIVE_JOB_LOOKUP_JSON=` rows, both `jobs` and `alternative_jobs`).
  Unsupported entity claims (e.g. "Rorze không có KTX" when no tool
  returned Rorze data) get a **hedging footer appended**. Sanitize-only:
  the body is preserved.
- **Empty retrieved set.** An empty `surfaced_ids` is treated as
  "nothing retrieved this turn"; any job-id citation is suspect. An empty
  `surfaced_entities` skips the entity check (no structured evidence to
  diff against); the agent-layer abstain path handles that case.

## Routing (router.py)

`backend/app/graph/router.py:route_turn` classifies a user turn into the
first retrieval strategy to try. It is intentionally cheap and never
calls an LLM; it annotates the turn so the agent starts from the right
retrieval path. The priority order matters:

```text
empty → general/agent
internal_retry_prompt → general/agent (so retries are not mis-classified)
out_of_scope_terms → out_of_scope / safe_redirect
fast_lane_match → small_talk / template  (greetings / thanks / goodbye / help)
timetable_terms → timetable / structured_lookup (search_bus_timetable)
contact_terms OR phone regex → contact / structured_lookup
recommendation_terms → recommend / recommendation
profile_terms → profile_update / profile
vacancy_lookup → faq_detail / knowledge_lookup
detail_terms → faq_detail / knowledge_lookup
(else) general / agent
```

Diacritic-insensitive normalization is shared with `app.shared.domain.text.normalize_vietnamese_text`,
so phrasings with or without Vietnamese diacritics land in the same
bucket. `_NON_ROLE_ACCEPTANCE_PREFIXES` blocks false positives like "có
nhân viên" being treated as "có nhận".

### Model-tier selection

`should_use_fast_model(route)` returns True for strategies in
`FAST_MODEL_STRATEGIES = frozenset({"template", "knowledge_lookup", "safe_redirect"})`.
The caller still verifies a fast model is configured before swapping;
the predicate only encodes eligibility so the policy lives in one place
alongside the intent taxonomy. Recommendation, profile, and general-agent
paths always use the reasoning model.

### Sort-intent detectors

- `detect_salary_sort_intent(user_text)` — Vietnamese diacritic-insensitive
  markers for "cao xuống thấp", "thấp lên cao", "sắp xếp / sx" without a
  direction defaults to `salary_desc`. Returns `None` when neither salary
  keywords nor markers match, so callers keep the default `updated_at`
  ordering.
- `detect_recency_sort_intent(user_text)` — matches "gần nhất", "mới nhất",
  "vừa mới", "mới đăng", "mới đăng tuyển", "gần đây" and returns
  `"created_at"` when the intent is present. In Vietnamese recruitment
  "gần nhất" / "mới nhất" means temporally most recent, not geographically
  nearest — the docstring locks this interpretation.

## Fast lane (zero LLM)

`backend/app/graph/fast_lane.py` answers common **non-factual** traffic
with zero LLM calls. Wired into `run_turn` *before* the agent, it
matches:

- Exact greetings / thanks / goodbye / help-meta phrases → Vietnamese
  template replies in persona voice (tôi/bạn per `persona.md`).
- Help/meta uses word-boundary keywords but only resolves to a generic
  "what I can help with" menu.

The lane is **deliberately narrow**: factual questions (salary, shuttle,
work location, contacts, interview schedule, age/KTX requirements) fall
through to the RAG + agent path. Wrong contact or pay information from a
hardcoded template is far worse than a slightly slower correct answer.
Add factual-intent fast-laning only behind a KB-confidence gate; the
persona-voice guard test pins tôi/bạn on every template.

## Pre-send claim fence

The final gate before any wire bytes is `svc.claim_send(conv,
version_at_start, lock_owner, pending_message_id, reply, outbox_channel,
outbox_payload)`. It runs server-side and atomically transitions the
pending message row PENDING → SENDING, gated on:

- The conversation version matching `version_at_start`.
- The DB lock still being held by `lock_owner` (re-derived against the
  live row).
- The retry stamp matching the pending message id.

A `rowcount=0` outcome yields `outcome="suppressed"` with the reason
returned to the caller; the recruiter sees the row as
`log_suppressed` rather than an empty "Gửi lỗi" bubble. Combined with
`truncate_for_chat` and `retry_exhausted_fallback`, a failed send is
always diagnosable — never silent.

## Why this order matters

- **Fast filter first.** Cheap deterministic checks handle 95%+ of cases
  with no remote judge call. Latency budget stays under the SLA and the
  LLM judge is reserved for genuine ambiguity.
- **Retry at most once.** A retry storm would multiply the LLM cost and
  the latency; capping at one rewrite plus a deterministic fallback
  guarantees the user always gets a Vietnamese answer.
- **Grounding before send.** A reply that cites job IDs the agent never
  saw is the highest-impact hallucination class; sanitizing at the
  pre-send boundary keeps that class out of the inbox.
- **Claim fence last.** Ownership + version + lock liveness are the only
  conditions that must hold **at the moment of send**. Re-checking
  earlier cannot close the TOCTOU; the fence must be the final gate.
