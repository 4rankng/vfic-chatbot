---
type: observability
title: Decision trace, audit log, and bot_runs resource
description: How every bot execution is recorded (allowlisted control-flow events only), how audit is appended, how decision traces are bounded and pruned, and how the bot_runs API surfaces them to recruiters.
tags: [observability, decision-trace, audit, bot-runs, retention, pii-redaction]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
sources:
  - id: openwiki-source-7e6a9dc23433aa6dfaa372aa
    resource: repo://backend/app/api/bot_runs.py
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-c1d0d5024df77f0640b1eea9
    resource: repo://backend/app/graph/decision_trace.py
  - id: openwiki-source-6201c1a523eb3beb2c1d8be9
    resource: repo://backend/app/graph/runner.py
  - id: openwiki-source-55002f5b1d39cf35fd6d60e2
    resource: repo://backend/app/main.py
  - id: openwiki-source-d8298ce2e49ec758107bef0b
    resource: repo://backend/app/models/conversation.py
  - id: openwiki-source-b5f84735f6183381fdd77f5c
    resource: repo://backend/app/schemas/bot_run.py
  - id: openwiki-source-fc120c8d11676fc7f2a9214a
    resource: repo://backend/app/services/audit_service.py
  - id: openwiki-source-e0d0321c41e65326116153dc
    resource: repo://backend/app/services/bot_run_service.py
  - id: openwiki-source-085098b884681cab422762c1
    resource: repo://backend/app/services/integration_settings.py
  - id: openwiki-source-54372f2d9834a49eaebe0cb9
    resource: repo://backend/app/workers/decision_trace_retention_worker.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

Every interactive bot turn records two parallel artifacts: an **append-only
audit row** for privileged actions (admin updates, role changes, secret
rotations) and a **bot_run row** that captures the turn itself — the proposed
reply, the outcome, the per-stage timing, the optional decision trace, and
the runtime authority fingerprint that signed the run. The two together
give recruiters and admins the operational trail they need without ever
persisting prompts, candidate text, evidence, tool payloads, or exception
contents.

## Bot-run persistence

`bot_runs` is owned by `app/models/conversation.py:BotRun`. Every
interactive turn writes one row; the runner records a PENDING entry on
enqueue (`record_bot_pending`) and a final outcome entry at the end
(`record_bot_outcome` → `BotRun.stage_timings`).

| Column | Notes |
|---|---|
| `id` | BigInteger identity, primary key |
| `conversation_id` | FK to `conversations.id`, cascade delete |
| `started_at`, `ended_at` | UTC timestamps; `ended_at < now() - retention_days` is the deletion predicate |
| `version_at_start` | Optimistic-concurrency version from the conversation row at start |
| `proposed_reply` | The bot's draft; may echo candidate content (writes are bot-side only) |
| `outcome` | `BotRunOutcome` enum (no separate Postgres type — `create_type=False`) |
| `stage_timings` | JSONB of per-stage wall-clock milliseconds + queue depth + token usage + tool breakdown + retried 429 + degraded flag. Aggregated via `percentile_cont` over the JSONB key path |
| `trace_id` | UUID propagated from the webhook request_id through RQ → `BotRunState` → LangGraph → Zalo send so one query returns every log line for one candidate message |
| `runtime_revision_id` | FK to `installation_manifest_revisions.id` (RESTRICT) — the persona/knowledge revision that was active at run time |
| `authority_generation` | Monotonic generation number — bumped on every authority edit |
| `runtime_fingerprint` | SHA-like checksum of the authority at run time |
| `outcome_metadata` | Phase 4 FAQ-bypass provenance: similarity_score, runner_up_score, decision_threshold, faq_document_id, abstained |
| `decision_trace` | Optional JSONB; see below |

## Decision trace (allowlisted, bounded)

`backend/app/graph/decision_trace.py:DecisionTraceBuilder` collects the
trace that ultimately lands in `BotRun.decision_trace`. The class is built
on three hard size caps declared in `backend/app/schemas/bot_run.py`:

| Cap | Default | Source |
|---|---|---|
| `MAX_DECISION_TRACE_EVENTS` | 64 | `schemas/bot_run.py:14` |
| `MAX_DECISION_TRACE_BYTES` | 128 KiB serialized JSON | `schemas/bot_run.py:15` |
| `MAX_MODEL_REASONING_CHARS` | 16 KiB per event | `schemas/bot_run.py:16` |

### What the builder accepts

Only **model-turn events** are accepted. The builder exposes three sinks:

- `record_decision(code, summary_code)` — compatibility sink for runner
  instrumentation **excluded from v2 traces**.
- `record_tool_selection(name, selected_by)` — compatibility sink for
  policy/prefetch events **excluded from v2 traces**.
- `record_model_turn(phase, provider, model, reasoning, tool_names)` —
  the only sink that produces events in `DecisionTraceSnapshot`. The
  reasoning field is normalized (`reasoning_status = "returned" |
  "not_returned" | "truncated"`), truncated at `MAX_MODEL_REASONING_CHARS`,
  and tool names are filtered against the closed allowlist
  `_ALLOWED_MODEL_TOOL_NAMES` and capped at 8.

Prompts, candidate answers, tool payloads/results, evidence, and exception
contents are **never** passed to the builder. The allowlist is structural,
not enforced by post-hoc scrubbing.

### Bounding and snapshotting

`_append(event_type, **data)` increments the event count, validates the
event via the Pydantic schema (rejects silently with a warning on
`ValidationError`), and pops the event if the serialized trace would
exceed `MAX_DECISION_TRACE_BYTES`. `snapshot()` returns
`DecisionTrace(version=2, events=[...], truncated=self._truncated)`;
`snapshot_payload()` returns a JSON-safe dict or `None` if the trace
fails validation or exceeds the size cap (logged, not raised).

The runner calls `snapshot_payload()` at the end of each turn and stores
the result on `BotRun.decision_trace`. The runner's `record_decision` /
`record_tool_selection` calls remain — they are the legacy sinks the
builder keeps for compatibility — so the runner does not need to be
rewritten when the schema evolves.

## Retention

`backend/app/workers/decision_trace_retention_worker.py` runs on
`decision_trace_retention_interval_seconds` (default **86400 s = 24 h**,
registered in `backend/app/main.py` lifespan via
`register_unique_tick`). Each tick:

1. Reads the latest
   `decision_trace_retention_batch_size` (default **200**) BotRun ids
   whose `decision_trace IS NOT NULL`, `ended_at IS NOT NULL`, and
   `ended_at < now() - decision_trace_retention_days` (default **30
   days**), ordered by `ended_at asc, id asc`.
2. Updates them with `decision_trace = NULL` (no row deletion — the
   bot_run history itself is preserved).
3. Commits and logs the cleared count.

The retention tick interval is `Settings.decision_trace_retention_interval_seconds`,
the retention window is `Settings.decision_trace_retention_days`, and the
batch cap is `Settings.decision_trace_retention_batch_size` — all env-
tunable without code changes.

## Bot-runs API

`backend/app/api/bot_runs.py` is the recruiter-visible surface.

| Method | Path | Visibility | Notes |
|---|---|---|---|
| `GET /api/v1/bot_runs` | list | Any authenticated user (`get_current_user`) | Filter by `conversation_id` and `outcome`; paged (`page`, `per_page`, max 200). Read-only ops audit trail; both admin + recruiter may view. |
| `GET /api/v1/bot_runs/{run_id}` | detail | `require_admin` | Returns the trace detail via `BotRunService.get_trace_detail`. 404 if missing. |

The header comment on the module is explicit: writes are **bot-side
only**; both roles can read, but only the bot pipeline ever writes a row.
This matches the frontend's automation page, which surfaces bot runs as a
diagnostic.

### Filtering by conversation and lead

`BotRunService.list` (`backend/app/services/bot_run_service.py`) takes
optional `conversation_id` and `outcome` filters. The query is built
incrementally: `SELECT BotRun WHERE conversation_id = ? [AND outcome = ?]`
and counted via `SELECT count(*) FROM (subquery)`. Results are ordered
`started_at DESC, id DESC` so newest runs come first; pagination is
`OFFSET (page-1)*per_page LIMIT per_page`. The companion
`list_conversation_trace_summaries` projects `decision_trace` summaries
per conversation (paged to 10 by default) for the conversation timeline
view.

## Audit log

`backend/app/services/audit_service.py:record_audit` is the single
helper for append-only audit rows. It inserts an `AuditEvent` (model
defined in `backend/app/models/audit.py`), populates `actor_id`, `action`,
`target_type`, `target_id`, and `payload`, and flushes — it does **not**
commit, so callers can compose an audit row with other writes in one
transaction.

Privileged actions wired through `record_audit` include:

- Integration secret rotations — `update_zalo_integration_settings`,
  `update_minimax_integration_settings`,
  `update_openrouter_integration_settings`, OA token refresh outcomes.
- Token refresh — the OA token-refresh path records before and after
  rows so a stuck refresh is auditable.

The pattern is consistent across the codebase: `await record_audit(...)`
followed by `await db.commit()`, then the local-cache eviction and
namespace-version bump.

## What never lands in storage

The trace builder accepts only allowlisted model-turn events and never
records prompts, candidate text, evidence, tool payloads, or exception
contents. The audit `payload` field stores **changed keys** (never
values) for secret rotations. The runtime invariants — `Settings`
rejects boot when `JWT_SECRET` or `INTEGRATION_SETTINGS_ENCRYPTION_KEY`
remains the dev default; the audit module never logs ciphertext or
plaintext; the trace builder's `record_model_turn` truncates oversized
reasoning rather than failing the turn — together ensure that the
storage shape never becomes a PII or secret sink.
