# Brainstorm: Messaging-Hardening Patterns Worth Adopting

**Date:** 2026-07-12
**Source:** External enterprise-messaging architecture review (WhatsApp/Slack/Twilio-scale)
**Scope:** Adapt only what survives YAGNI at VFIC scale (single-tenant, 2 vCPU droplet, modest traffic)
**Status:** Approved for planning — 4 items selected

---

## Context

An external review proposed 7 enterprise-messaging improvements against the verified
pipeline (`docs/system-architecture.md` §2.1). Each claim was verified against source.
Most recommendations are **over-built for VFIC's scale**; several are **factually wrong**
about the code. This report covers the 4 items the user selected after triage.

## Verification Triage (for the record)

| Review claim | Verdict | Why |
|---|---|---|
| "No transactional outbox" | TRUE, **mitigated** | Inbound commits before enqueue → 503 → Zalo retries → reconcile sweep. Equivalent durability at this scale. **Not adopting.** |
| "Need 14-state turn machine" | OVERKILL | Have 8 `DeliveryStatus` + 3 `BotRunOutcome`. Adding `SEND_UNKNOWN` is enough. |
| "Generation/delivery worker split" | PREMATURE | One OA account, modest traffic. Adds process + queue + failure mode for zero benefit. |
| "Per-tool idempotency journal" | **WRONG PREMISE** | All 7 LLM tools (`tools.py:478`) are pure read-only retrievals. Zero mutations. |
| "Coordinated OA token refresh w/ token_version" | **ALREADY DONE** | `integration_settings.py:416` has Redis `SET NX EX 30` + loser-poll. Only the `token_version` shortcut is missing — marginal for one account. |
| "Send reply THEN persist candidate = user told success before commit" | **MISLEADING** | `persist candidate` is lead EXTRACTION (idempotent upsert into own DB), not an external business transaction. Risk doesn't apply. |
| "Reconciler blindly retries all failures" | PARTIAL | Classifies by symptom (stale_pending / failed_send / unanswered_inbound), not root cause. Fine at this traffic. |
| "No `send_attempt` / `SEND_UNKNOWN`" | **TRUE — real gap** | Only `Message.delivery_status` flip. Transport timeouts → FAILED → reconciler re-runs → **duplicate reply risk.** |

---

## Selected Items (4)

### 1. `SEND_UNKNOWN` DeliveryStatus — the one real bug

**Problem.** When the Zalo HTTP POST raises a read timeout / connection reset *after*
the request may have reached Zalo, `ZaloBotSender._post` / `ZaloOASender._post` wraps
it as `SendResult(ok=False)`. The message flips to `FAILED`; the reconcile sweep
(~60s) re-enqueues the whole turn → the LLM regenerates → candidate receives two
replies. At-most-once SENDING→SENT recovery (`state.py:539`) only covers worker
crashes, not this.

**Approach.**

- Add `SEND_UNKNOWN = "SEND_UNKNOWN"` to `DeliveryStatus` (`models/conversation.py`).
- Classify transport errors at the sender boundary: distinguish *pre-send connection
  failures* (retryable) from *post-send-ambiguous timeouts* (SEND_UNKNOWN). Heuristic
  in `zalo_bot_service._post` / `zalo_oa_service._post`: `httpx.ReadTimeout` /
  `httpx.RemoteProtocolError` after bytes were written → SEND_UNKNOWN;
  `httpx.ConnectError` / pre-write failures → keep as retryable FAILED.
- Reconciler (`reconcile_worker.py`) skips SEND_UNKNOWN rows — no automatic retry.
  Surface them on the recruiter console as "gửi không xác định — cần kiểm tra"
  for manual confirm/cancel.
- Add a lightweight `SendAttempt`-style provenance: stamp `Message.external_error`
  with `transport:read_timeout` vs `transport:connect_error` so the classification
  is auditable. **No new table** — reuse `messages.external_error` + a new
  `messages.send_outcome` enum column if the existing `delivery_status` feels
  overloaded (TBD in plan).

**Acceptance criteria.**
- A simulated read-timeout after Zalo accepts the message produces a single reply
  to the candidate, not two.
- SEND_UNKNOWN messages appear on the console flagged for manual review.
- Reconciler logs "skipped SEND_UNKNOWN: N" each sweep instead of re-enqueuing.

**Risk.** Heuristic misclassification (false SEND_UNKNOWN on a genuinely-failed send)
leaves a message undelivered. Mitigation: manual "resend" action on the console for
SEND_UNKNOWN rows — recoverable by a human in seconds.

**Effort:** S (one enum value + two classifier branches + reconciler skip + console flag).

---

### 2. Observability metrics on the performance page

**Problem.** `BotRun.stage_timings` JSONB is already collected but almost nothing is
surfaced. The review's metric list is the most valuable section of the whole document
and you're missing ~90% of it.

**Approach.** Add a metrics rollup that reads from existing tables (no new instrumentation
columns needed for most). Prioritized list:

| Metric | Source | Value |
|---|---|---|
| Webhook ACK latency (p50/p95) | already logged | user-perceived speed |
| Queue age at pickup | `BotRun.stage_timings.queue_ms` | backpressure signal |
| Turn execution latency (p50/p95) | `BotRun.stage_timings.total_ms` | core SLO |
| Dedup rate (claims vs duplicates) | `message_dedup` inserts | health signal |
| FAQ fast-lane hit rate | `BotRun.outcome = faq_cache` | cost saving |
| **Semantic FAQ abstention rate** | `BotRun.outcome` + new provenance (item 3) | **tuning gold** |
| LLM latency (queue vs model) | `stage_timings.llm_queue_ms` / `llm_model_ms` | semaphore sizing |
| Tool latency per tool | `stage_timings.tools[*]` | retrieval health |
| 401 / token-refresh rate | integration_settings audit | OA health |
| Human-takeover cancellation rate | `BotRun.outcome = SUPPRESSED` + reason | mode config tuning |
| Ambiguous-send count | item 1 SEND_UNKNOWN | delivery health |
| Reconcile recovery count | reconcile worker logs | reliability |

**Acceptance criteria.**
- Performance page shows the top 6 metrics as time-series (last 24h / 7d toggle).
- Semantic-FAQ abstention rate is queryable (requires item 3 provenance).
- No new heavy instrumentation — reuse existing `stage_timings` + `BotRun.outcome`.

**Risk.** Over-querying `bot_runs` JSONB at 7d window on a 2 vCPU box. Mitigation:
materialize a daily rollup table or Redis-cached aggregates (TTL 5min). Decide in plan.

**Effort:** M (mostly frontend + one aggregation query; the data already exists).

---

### 3. Semantic-FAQ provenance — tune the threshold with data

**Problem.** `faq_bypass.try_answer` (`graph/runner.py:338`) returns a canonical KB
answer when embedding similarity clears a single threshold. Currently there's no
record of *how confident* the match was or *what the runner-up was*. False positives
deliver wrong FAQ answers; you can't see them.

**Approach.** Store provenance on FAQ-bypass outcomes:

```
BotRun.outcome_metadata = {
  "faq_document_id": "...",
  "faq_version": 7,
  "similarity_score": 0.87,
  "decision_threshold": 0.82,
  "runner_up_score": 0.81,   # ← the gold field
  "retrieval_filters": {...}
}
```

- **Abstain on low margin:** if `top_score - runner_up_score < margin` (e.g. 0.05),
  fall through to the LLM instead of trusting the FAQ. Margin tuning becomes data-driven.
- Wire abstention events to outcome `faq_bypass_abstained` so item 2 can count them.
- Keep threshold + margin configurable via `IntegrationSetting` or a settings flag
  (avoid hardcoding).

**Acceptance criteria.**
- Every FAQ-bypass BotRun carries similarity + runner-up + threshold.
- Low-margin matches fall through to the LLM (counted as abstained).
- Performance page shows abstention rate over time (depends on item 2).

**Risk.** Over-abstention pushes more traffic to the LLM → higher cost + latency.
Mitigation: start with a conservative margin (0.03–0.05), monitor for a week, tune.

**Effort:** S–M (requires `faq_bypass` adapter to return runner-up + adding a JSONB
column or reusing `outcome_metadata` if it exists).

---

### 4. `trace_id` propagation + `conversation_seq` for debugging

**Problem.** `request_id` middleware exists at the FastAPI boundary but does not flow
through RQ → LangGraph → Zalo send. Following one candidate message end-to-end across
logs requires manual correlation by `conversation_id` + timestamp. Ordering bugs
("did B process before A?") are unanswerable today.

**Approach.** Two small additions, **no fencing/epoch math** (your 4-layer guard
already closes the TOCTOU window — verified).

**(a) `trace_id` propagation:**
- Generate `trace_id` at webhook entry (reuse `request_id` or add a dedicated UUID).
- Add to the RQ job dict (`chatbot_worker.enqueue_chat_run`).
- Add to `BotRunState` (`graph/types.py`).
- Include in every structured log line via logging context (`app/core/logging.py`).
- Stamp on `BotRun.trace_id` column for post-hoc query.

**(b) `conversation_seq` column (debugging aid only):**
- Add `conversations`/`messages` monotonic per-conversation sequence (or reuse
  `conversation.version` if it already increments on every mutation — verify in plan).
- Pure observability; no fencing logic consumes it.

**Skip:** full `event_seq` resumable Socket.IO, ownership epochs, fencing tokens.
The review's full ID list (`webhook_event_id`, `turn_id`, `send_attempt_id`,
`provider_message_id`, `ownership_epoch`) is over-engineering for this scale.
`trace_id` + `conversation_seq` is the 80/20.

**Acceptance criteria.**
- One log query by `trace_id` returns every line for a single webhook event's journey.
- `conversation_seq` lets you answer "which message processed first" without guessing.
- No behavior change — pure instrumentation.

**Risk.** `conversation.version` may already serve the seq purpose; adding a duplicate
column is DRY violation. Mitigation: verify in plan, reuse if possible.

**Effort:** S (trace_id is a clean propagation chain; seq column is one migration).

---

## Explicitly NOT Adopting (YAGNI)

- Transactional outbox — pre-commit + 503 + reconcile is equivalent at this scale.
- 14-state turn machine — 8 + SEND_UNKNOWN is enough.
- Generation/delivery worker split — premature for one OA account.
- Per-tool idempotency journal — all tools are read-only (wrong premise).
- OA token_version reload shortcut — current Redis lock + poll is fine.
- Full event-sourced Socket.IO recovery — "refetch on reconnect" covers 99%.
- Ownership epoch/fencing — 4-layer `claim_send` guard already closes TOCTOU.

---

## Open Questions for Plan Phase

1. **Item 1:** Add a new `send_outcome` enum column, or reuse `delivery_status` +
   `external_error`? Decision affects migration shape.
2. **Item 2:** Materialized daily rollup table, or Redis-cached aggregates (TTL 5min)?
   2 vCPU constraint matters here.
3. **Item 3:** Does `BotRun` already have an `outcome_metadata` JSONB column, or does
   this need a migration? (Scout didn't confirm.)
4. **Item 4:** Reuse `conversation.version` as the seq, or add a dedicated column?
5. **Sequencing:** Item 3 depends on item 2 (abstention rate needs metrics surface).
   Item 1 and item 4 are independent. Plan should phase accordingly.

---

## Next Step

Recommend `/ck:plan --tdd` for items 1 and 3 (they modify critical send + FAQ paths
where regression risk is real and existing tests can lock behavior first), and
default `/ck:plan` for items 2 and 4 (additive instrumentation). Or one combined plan
with phased ordering: 1 (bug fix, standalone) → 4 (instrumentation, standalone) →
3 (needs 2's surface) → 2 (aggregation).
