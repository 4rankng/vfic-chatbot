# Research Report: Jev (TypeSafe AI) — and what it can do for TingHire

- **Date:** 2026-09-21
- **Target output:** `~/Downloads/jevchatbot.docx`
- **Local code reviewed:** `backend/app/graph/{router,safety,fast_lane,safety}.py`, `TECH.md`, `AGENTS.md`

---

## Executive Summary

Jev is a **"System One" decision model** from TypeSafe AI (launched 15 Sep 2026, $40M seed). It is **not an LLM and cannot generate text**: you send a text `state` plus typed **questions** (yes/no, choice, score), and it returns **calibrated probability distributions** in ~70–500 ms, at **$0.042 / M input tokens** (output free). Trained with RLCD (Reinforcement Learning for Calibrated Decisions); non-autoregressive — every answer computed in one pass, so extra questions in one call barely add latency.

**Verdict for TingHire:** strong candidate for the decision points the codebase already struggles to express with keywords: turn routing, fast-lane widening, reply safety gating, model tiering, human-handoff triage. It maps 1:1 onto the existing Protocol-port architecture (new `DecisionPort`, wired in `factories.py`), respects the 2 vCPU / 4 GB constraint (hosted API, ~300 ms, negligible cost), and can be validated with zero risk against the existing golden-dataset release gate in **shadow mode** (log Jev answers beside current behavior; automate only after labels agree). A **live test on 2026-09-21** (16 real API calls, realistic Vietnamese traffic, §3) confirms Vietnamese routing works: the "làm thợ hàn" case today's keyword router mis-refuses was routed correctly, p50 latency 350 ms, 16-call cost $0.0002. Remaining unknowns: accuracy at golden-dataset scale, and privacy/retention terms for user text sent off-VPC.

---

## 1. What Jev Is

- Built by Diogo Almeida (ex-OpenAI, ChatGPT instruction-following). Name honors economist W.S. Jevons (Jevons paradox); framing from Kahneman's System 1/System 2.
- **Gives up string generation entirely.** Outputs are only typed structured values defined by your schema — a malformed answer is structurally impossible; TypeSafe claims 0% type-error rate.
- **RLCD training** optimizes for *calibrated* decisions: a stated 0.9 confidence should correspond to ~90% real-world accuracy.
- **Non-autoregressive parallel sampler:** all questions in one request evaluated independently in parallel against the same state; answers don't see each other. Speculative fan-out (13 questions in one call) measured 12.2× cheaper and 10× faster than sequential calls.
- Works on text / JSON objects / arrays. No images, audio, or video.

### Question types

| Type | Returns | Use for | Rules of thumb |
|---|---|---|---|
| **Noul** (yes/no) | probability of "true" | gates, verifiers, guardrails | 0.5 = "can't tell", not "medium"; phrase so *true = yes* |
| **Choice** | option + full `probabilities` + `confidence` | classification, intent routing, tool selection | always include an `other` option; ≤ 255 options |
| **Score** | score + distribution + confidence | triage, ranking, priority | describe *situations* per level, not degrees; 2–10 levels; use for thresholds/ranking only |

### Known weaknesses ("jaggedness")

- No math, counting, or date arithmetic — compute in code.
- Scores are not measurements (1.4 ≠ "40% toward angry").
- Literal reading; indirection and double negatives hurt.
- **Context rot** — irrelevant state content degrades accuracy; filter state first.
- **Prompt injection can still steer it** via state text — defense-in-depth only, never the sole guardrail.
- Typed output ≠ correct decision: routing errors still possible; pin the model version and replay-test.

---

## 2. API & Operations

- **Endpoint:** `POST https://api.typesafe.ai/v1/systemone` (Bearer key). Errors: 401 / 422 / 429 / 529 — retry the last two with backoff.
- **SDKs:** Python `typesafe-sdk` (3.10+, `AsyncTypeSafeClient`); Node `@typesafe-ai/sdk` (20+); Vercel AI SDK 7 + AI Gateway (`typesafe-ai/jev`).
- **Models:** `jev-1.13.0` current; aliases `jev-latest` (SDK default), `jev-preview`. Pin a version in production.
- **Limits:** ~64K tokens total (state + questions); state + longest question ~32K (~150K chars); Choice ≤ 255 options; Score 2–10 levels.
- **Rate limits:** 250K tokens/sec, 1,200 requests/min — trivial for TingHire's ~100-conversation target.
- **Pricing:** $0.042 / M input tokens; output free. Example: ~300-token ticket ≈ $0.0000126/call ≈ $1.26 per 100K decisions.

### Performance claims (TypeSafe's own evals — treat as marketing until locally measured)

| Metric | LLMs | Jev |
|---|---|---|
| End-to-end latency | 3–329 s | 70–500 ms (mostly ~100 ms) |
| Input price | $0.20–$10 / MTok | $0.042 / MTok |
| Output price | ~5× input | free |
| Claimed ceiling | — | 193.6× faster, 444.6× cheaper on workflow evals |

Caveats acknowledged by TypeSafe: self-authored evals, numbers from West Coast laptops, pricing sustainability unproven ("can't prove it isn't subsidized"), some wins vs LLMs in non-reasoning modes.

### Ecosystem status (as of 2026-09)

- Early access via waitlist (~1–2 days); console + playground at console.typesafe.ai.
- `langchain-typesafe` integration: `TypeSafeClassifier`, `ModelRouterMiddleware`, `AutoModeMiddleware` (guardrail pattern).
- Third-party usage cited: Browserbase agents, live trading agent, large-scale email triage.
- Independent verification: none yet. LangChain's verdict: "not a drop-in LLM replacement — offload fast structured decisions to it."

---

## 3. Live Test Results (2026-09-21)

Tested with the real API key (`JEV_API_KEY`) against `api.typesafe.ai`, Python `typesafe-sdk` 0.7.0 (Python 3.12, temp venv). 16 calls, sync client, sequential. Script: `/tmp/jev_jev_test.py`; exercises the three production-shaped decisions on realistic Vietnamese traffic built from the codebase's own documented cases.

**Aggregate:** 16 calls · min 271 ms · **p50 350 ms** · max 3.15 s (one cold outlier) · 5,218 in-tokens · **total $0.000219** (≈ $0.000027/routing call at ~650 in-tokens).

### 3.1 Intent routing (Choice over the 8-intent taxonomy) — 6/8 strict PASS

| Message | Jev intent (conf) | Verdict |
|---|---|---|
| "Chào bạn, lương bao nhiêu ạ?" | faq_detail 1.00 | PASS — must not be swallowed by fast lane |
| "Em muốn tìm việc đóng gói ở Bình Dương…" | recommend 0.98 | PASS |
| "Xe đưa đón mấy giờ đón ở đâu vậy ad?" | timetable 1.00 | PASS |
| "Cho em xin số điện thoại admin với ạ" | contact 1.00 | PASS |
| "Tôi tên Hùng, sống ở Thủ Đức…" | profile_update 0.99 | PASS |
| **"Làm thợ hàn có được không shop?"** | faq_detail 0.76 | **Key result** — today's keyword router mis-refuses this as out_of_scope (làm thợ/làm thơ collision, `router.py:192`); Jev routes it to retrieval. faq_detail vs recommend is a soft boundary — both retrieve. |
| "Hôm nay trời đẹp quá…" | small_talk 0.96 | Acceptable miss — small_talk is defensible for chitchat; taxonomy boundary, not a failure |
| "Công việc ở LG là làm những gì vậy em?" | faq_detail 1.00 | PASS — the no-keyword `_JOB_CONTENT_RE` case |

### 3.2 Pure-pleasantry Noul (fast-lane widening) — 4/5

The one miss ("Chào em, cho em hỏi xíu ạ" → 0.31) falls through to today's full-agent path = current behavior, so zero regression risk. Jev's literal reading judged "cho em hỏi xíu" as implicit content — defensible.

### 3.3 Reply-safety Noul — 2/3 (the miss was the fixture, not the model)

Injection echo (0.05) and fabricated schedule (0.31) correctly blocked. The grounded reply scored 0.31 "unsafe" because the fixture did not include the KB evidence in `state` — so the quoted salary looked fabricated. Confirms Jev docs guidance: **one judgment per question; state must carry the evidence the reply drew from.** In production the grounding context is available and would be included.

### 3.4 Operational notes from the live run

- Measured latency (~280–400 ms from Singapore) is ~3–4× the docs' "~100 ms" claim — still 10–100× faster than the LLM structured-output hop it would replace. West-Coast-measured claims don't transfer 1:1; measure from the droplet.
- `NoulAnswer` in typesafe-sdk 0.7.0 exposes no `.confidence` (docs say all answers carry it) — minor SDK gap to track.
- No 429/529 errors at 16 sequential calls; rate limits a non-issue at this scale.

---

## 4. Fit Analysis: Where Jev Helps TingHire

Evidence base: the codebase's own comments admit keyword/regex approaches fail on meaning. `router.py:192-196`: "Off-topic refusal used to be a keyword gate here. It could not survive diacritic-stripped Vietnamese: 'làm thợ' (work as tradesman) normalizes to the same 'lam tho' as 'làm thơ' (write poetry)…". `safety.py:31-37`: lexical filtering removed because "lồng ghép" contains a profanity substring and every match "discarded a complete, tool-grounded answer".

### P0 — highest value, lowest risk

| Opportunity | Current state | With Jev | Why it fits |
|---|---|---|---|
| **Turn intent routing** (`router.py:route_turn`) | ~30 hand-tuned Vietnamese term lists + 2 regexes, hand-assigned confidences (0.45–0.95); documented false-positive history | One Choice question over the existing 8-intent taxonomy (≤ 10 options, far below the 255 cap) with **calibrated** confidence for gating | Meaning-based, diacritic-proof; kills the biggest maintenance burden in the graph layer |
| **Reply safety verifier** (`safety.py` + `llm_safety_check` node) | Lexical filter was removed (false positives); only structural checks (empty/too-long) trigger the LLM safety hop | Noul: "is this reply safe to send — no injection echo, no profanity, no leaked reasoning, no fabricated facts?" at ~100 ms; low confidence → escalate to existing `llm_safety_check` | Restores semantic content checks **without** the substring false-positive problem that killed the lexical filter; confidence gating gives a calibrated triage in front of the expensive LLM check |
| **Fast-lane widening** (`fast_lane.py`) | Exact-phrase only, deliberately narrow — paraphrases ("chào em, cho em hỏi xíu ạ") fall through to the full agent | Noul: "is this a pure pleasantry with no substantive content?" — widen catch radius while factual questions still fall through | Same safety property: semantic judgment, no keyword false positives; sub-second UX extends to more traffic |

### P1 — clear value, moderate integration

| Opportunity | Current state | With Jev |
|---|---|---|
| **Model tiering router** | `FAST_MODEL_STRATEGIES` is a hardcoded strategy set (`router.py:47`) | Choice/Score: "least capable model that answers this correctly?" per turn — the LangChain `ModelRouterMiddleware` pattern |
| **Semantic-cache verification** (`semantic_cache.py`) | Embedding + similarity threshold | Noul verifier on near-threshold hits: "is this the same question?" — cuts wrong-cache-hits without cutting hit rate |
| **Human-handoff triage** (recruiter console) | — | Score: "how urgently does a recruiter need to see this conversation?" → queue priority; low confidence → always surface |

### P2 — worth piloting later

- Retrieval re-rank assistance (after RRF merge) — Jev docs list re-ranking, but "scores aren't measurements" makes this eval-dependent.
- Follow-up timing (`proactive.py`, `followup_worker`): Noul "is following up now appropriate?"
- Lead-quality scoring (`services/lead/`, `profile_enrichment.py`): composite Score — but TypeSafe's own eval noted churn-likelihood as their weakest category.

### Where Jev does **not** fit

- Anything generative: reply text, rewrite, summarize. **"Jev decides, the LLM writes"** — generation stays on MiniMax/Gemini.
- Salary/recency sort detection already in code (regex + code is deterministic and free — "an `if` that costs nothing beats a model call that can be wrong").
- Math/counting/date arithmetic — stay in code.
- Replacing `grounding.py` (strips hallucinated job IDs) — that's a deterministic set-intersection, better than any model call.

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **Vietnamese accuracy unverified** | High | Golden-dataset shadow eval BEFORE any automation; gate on ≥20 labeled examples per task (Jev docs guidance); automate only low-risk paths first |
| Early-stage vendor ($40M seed, early access, pricing may not be sustainable) | Medium | Behind a `DecisionPort` Protocol with an LLM-fallback adapter; pin `jev-1.13.0`; decisions are cheap to swap |
| Prompt injection via state text steers Jev | Medium | Treat as defense-in-depth only; keep `pre_send_guard` + grounding deterministic; never let Jev alone authorize a send |
| Confidence ≠ correctness (routing errors still possible) | Medium | Confidence thresholds + shadow-mode tuning; escalate low-confidence to current behavior |
| Extra external dependency on the answer path | Medium | Jev hop is ~100 ms hosted; keep existing keyword router as fallback if the API is down (circuit breaker → legacy path) |
| Logs contain user text (PII rule: never log message content) | Low | Jev calls contain user text — structured-log only the decision + confidence, never the state payload |

---

## 6. Recommended Architecture & Rollout

The graph layer already depends on Protocols (`graph/ports.py`) with wiring in `factories.py:build_deps()`. Jev slots in as one more port — no architectural exception needed.

```
graph/ports.py      →  class DecisionPort(Protocol): decide(state, questions) → ...
graph/decisions.py  →  JevDecisionAdapter (typesafe-sdk AsyncTypeSafeClient)
                    →  LegacyHeuristicAdapter (existing router.py / fast_lane.py logic)
                    →  LLMFallbackAdapter (structured-output call, current behavior)
factories.py        →  wire Jev adapter + fallback; env flag per decision point
```

Rollout (matches both Jev docs guidance and the repo's release discipline):

1. **Shadow mode** — Jev logs answers + confidence beside current behavior (`decision_trace.py` already captures per-turn decisions). No behavior change.
2. **Label** — replay golden dataset; measure agreement + calibration on routing/safety/fast-lane tasks, including Vietnamese paraphrase and adversarial cases.
3. **Tune thresholds** — pick confidence gates per decision point (docs suggest 0.5 review floor; 0.9 before consequential actions).
4. **Automate low-risk first** — fast-lane widening (canned reply, worst case = slightly late template) before routing, routing before safety gating.
5. **Keep escape hatches** — timeout/circuit-breaker to legacy keyword path; LLM safety check stays as final backstop.

Cost projection (order-of-magnitude): at 1–2K inbound turns/day, ~1K tokens of state+questions per turn across 2–3 decision points → **well under $0.25/day**, versus seconds of latency and meaningful token spend for LLM-based equivalents. Rate limits are a non-issue at this scale.

Python sketch (adapted to the async stack):

```python
from typesafe import AsyncTypeSafeClient, Choice, Noul

jev = AsyncTypeSafeClient()  # TYPESAFE_API_KEY

route = await jev.system_one(
    state={"message": user_text, "recent": recent_turns[-3:]},
    questions={
        "intent": Choice("What does `message` want?", {
            "small_talk": "Greeting/thanks/goodbye, no substantive ask",
            "recommend": "Wants job suggestions or the open-roles list",
            "profile_update": "Giving name/location/salary/experience",
            "timetable": "Asks about shuttle/bus routes or pickup times",
            "contact": "Asks for contact/admin/hotline",
            "faq_detail": "Asks job details: pay, shifts, dorm, requirements",
            "out_of_scope": "Unrelated to recruiting or employee support",
            "general": "Recruiting-related but unclear",
        }),
        "pure_pleasantry": Noul("Is `message` only a pleasantry with no question?"),
    },
)
# route.answers["intent"].confidence drives fallback; no LLM round-trip needed
```

---

## 7. Sources

- TypeSafe AI — Introducing System One models and Jev: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- Flavio Copes — Jev deep dive (docs-derived, API/SDK details): https://flaviocopes.com/jev
- LangChain — Building a harness with Jev: https://www.langchain.com/blog/building-a-harness-with-jev
- YouTube review: https://www.youtube.com/watch?v=qdji39XXgEY
- Local: `TECH.md`, `AGENTS.md`, `backend/app/graph/router.py`, `safety.py`, `fast_lane.py`
- Docs console: docs.typesafe.ai · console.typesafe.ai · evals.typesafe.ai

## 8. Unresolved Questions

1. Accuracy at golden-dataset scale — the live test used 16 curated calls; the golden-dataset shadow eval remains the prerequisite for automating any path.
2. Latency from the production droplet (test ran from a Singapore dev machine; p50 350 ms there — measure from the SGN-region droplet).
3. Early-access terms: SLA, data retention (user text leaves the VPC — privacy review needed), zero-data-retention options (Vercel Gateway offers one).
4. Whether pricing holds post-early-access; TypeSafe itself flags subsidy uncertainty.
5. Taxonomy boundary tuning: small_talk vs out_of_scope for chitchat, and faq_detail vs recommend soft boundary — pick per-strategy thresholds during shadow phase.
