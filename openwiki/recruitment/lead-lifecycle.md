---
type: wiki
title: "Lead pipeline: capture, enrichment, kanban, events"
description: "Lead capture from inbound webhooks, persistence_low enrichment, kanban stages/tags/assignee, lead events, and chatops shortcuts."
tags: [leads, kanban, enrichment, candidate-extraction, chatops, follow-up, lead-score, zalo]
sources:
  - id: openwiki-source-e4225e8ec527cd572e3a6fe0
    resource: repo://backend/app/recruitment/domain/statuses.py
  - id: openwiki-source-9bfa54d53d851b6aa085f0ba
    resource: repo://backend/app/services/candidate_extraction.py
  - id: openwiki-source-1f63e5ef72cb712bb3a76c3e
    resource: repo://backend/app/services/lead/chatops.py
  - id: openwiki-source-2334db381b6930083346dd88
    resource: repo://backend/app/services/lead/events.py
  - id: openwiki-source-dae946bb7963054ee29e4b4e
    resource: repo://backend/app/services/lead/normalizers.py
  - id: openwiki-source-246640c87bb50c03c8815568
    resource: repo://backend/app/services/lead/service.py
  - id: openwiki-source-bce480b49c9a9f0493b5b435
    resource: repo://backend/app/services/profile_enrichment.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
---

# Lead pipeline: capture, enrichment, kanban, events

Every candidate who messages the bot becomes a *lead* — a CRM row that tracks
their profile, stage, score, assigned recruiter, and follow-up tasks. The lead
lifecycle is the bridge between the bot conversation and the recruiter console.

## Lead model (`backend/app/models/lead.py`)

| Field | Type | Purpose |
|---|---|---|
| `id` | `BigInteger` (auto) | Primary key |
| `contact_id` | `UUID` FK → `contacts` | Canonical contact (Alembic 0047) |
| `zalo_id` | `String` | Zalo-only compatibility alias (NULL for Messenger leads) |
| `name`, `phone`, `birth_year`, `age`, `living_area`, `address`, `gender`, `region` | text/int | Candidate profile fields |
| `desired_job`, `years_experience`, `expected_salary` | text | Job preferences |
| `lead_stage` | enum | `NEW` → `CONTACTING` → `REGISTERED` / `SKIPPED` |
| `lead_score` | enum | `hot` / `warm` / `not_interested` |
| `intent_score` | `Numeric(3,2)` | LLM-derived intent confidence |
| `qualification_reasons` | `ARRAY(Text)` | Why the lead was scored this way |
| `next_action_at` | `DateTime(tz)` | When the next follow-up is due |
| `assigned_recruiter_id` | `UUID` FK → `users` | Recruiter who owns this lead |
| `version` | `Integer` | Optimistic-lock token |
| `notes` | `Text` | Recruiter notes |

### Stages (`LeadStage`)

```
NEW → CONTACTING → REGISTERED
                ↘  SKIPPED
```

| Stage | Vietnamese | Meaning |
|---|---|---|
| `NEW` | *Mới* | Just captured, no recruiter action yet |
| `CONTACTING` | *Đang liên hệ* | Recruiter is actively engaging |
| `REGISTERED` | *Đã đăng ký* | Candidate completed registration |
| `SKIPPED` | *Bỏ qua* | Not a fit, archived |

### Scores (`LeadScore`)

| Score | Meaning |
|---|---|
| `hot` | High intent — actively looking, responsive |
| `warm` | Interested but not urgent |
| `not_interested` | Explicit opt-out or no interest |

## Capture path

Lead capture happens in the Zalo webhook path. When a candidate messages the
bot:

1. The webhook commits the inbound message and enqueues onto `webhook_high`
2. `candidate_extraction.py` runs an LLM call that returns both structured CRM
   fields and memory facts in a single pass
3. `normalize_lead()` applies Vietnamese diacritic-insensitive phone/name
   normalization
4. `extract_self_reported_name()` pulls the candidate's name from their
   message text (with context from the previous bot message)
5. The lead row is upserted — new leads get `lead_stage=NEW`, existing leads
   are patched with any new fields

The extraction pipeline uses `CandidateExtractionUseCases` which is
constructed with the normalizer, `parse_memory_facts`, and
`normalize_vietnamese_text`. A greeting gate skips extraction for pure
greetings (no candidate data to extract).

## Enrichment (`profile_enrichment.py`)

After each SENT reply, the `persistence_low` queue runs OA profile
enrichment:

1. Fetches the Zalo OA display name for the candidate's `zalo_id`
2. Stores it on the canonical `Contact` (not directly on `Lead`)
3. The candidate extraction LLM separately decides whether the display name
   is suitable evidence for `Lead.name`

Enrichment is best-effort and rate-limited:
- `_PROFILE_LOOKUP_DONE_TTL_SECONDS` (7 days) — a Redis key prevents
  re-fetching for a week
- `_PROFILE_LOOKUP_LOCK_TTL_SECONDS` (15s) — a Redis lock prevents
  concurrent lookups for the same `zalo_id`
- `_PROFILE_LOOKUP_WAIT_SECONDS` (3.0s) — max wait for an in-flight lookup

## Kanban board (`LeadService.board`)

The kanban view groups leads into sections:

1. **Cần trả lời** (*needs reply*) — priority section: leads with unanswered
   conversations or due follow-ups
2. **Mới** (*NEW*) — new leads
3. **Đang liên hệ** (*CONTACTING*) — actively engaged
4. **Đã đăng ký** (*REGISTERED*) — completed registration
5. **Bỏ qua** (*SKIPPED*) — archived

Sorting within each section: `hot` → `warm` → `not_interested` (priority
order), then by the requested sort column. The `needs_reply` section uses
additional attention ordering: unanswered conversation → due follow-up →
hot score.

### Filtering and search

`LeadService.list` supports:
- `stage` filter
- `needs_reply` / `exclude_needs_reply` — attention-first views
- `zalo_id` / `zalo_ids` — direct lookup
- `q` — Vietnamese diacritic-insensitive search across name, phone,
  desired_job, zalo_id (using `unaccent` extension)
- Sort by: `updated_at`, `created_at`, `name`, `lead_stage`, `lead_score`

## Optimistic concurrency

`LeadService.update` uses optimistic concurrency:
- Incoming `version` is compared to the DB row's `version`
- On mismatch: `ConflictError("lead was modified by another recruiter")`
- On success: `version += 1`, commit, publish `lead.updated` event
- No version provided: trusted internal callers apply direct updates

## Tags (`lead/tags.py`)

Tags are a freeform label system on leads. The tag library manages
creation, assignment, and removal. Tags are used for segmentation and
filtering in the recruiter console.

## Events (`lead/events.py`)

`LeadEventBus` publishes lead realtime events through the Socket.IO bridge:

- `lead.updated` — published on every lead mutation (stage change, score
  update, profile enrichment, recruiter edit). Payload includes the full
  `LeadOut` serialization plus optional `actor_name`.

Events are routed to `lead:<lead_id>` rooms so recruiters who have joined
that lead's detail view see the update in real time.

## ChatOps (`lead/chatops.py`)

`ChatopsService` provides recruiter quick-actions from the conversation view:

| Action | Vietnamese | Effect |
|---|---|---|
| `mark_contacting` | *Đánh dấu đang liên hệ* | Stage → CONTACTING |
| `schedule_followup` | *Lịch hẹn follow-up* | Creates a `FollowUpTask` |
| `mark_not_interested` | *Đánh dấu không quan tâm* | Score → not_interested |
| `mark_registered` | *Đánh dấu đã đăng ký* | Stage → REGISTERED |

`build_assist` constructs the assist panel: summary, missing fields,
suggested reply, next action, mode label, signals, and recent messages.

## Follow-up tasks (`FollowUpTask`)

| Field | Purpose |
|---|---|
| `lead_id` | FK → lead |
| `assigned_to` | FK → user |
| `due_at` | When the follow-up is due |
| `status` | `PENDING` / `DONE` / `SKIPPED` / `CANCELLED` |
| `notes` | Task notes |

The proactive follow-up tick (see `openwiki/recruitment/proactive-followup.md`)
checks for due tasks and sends reminders.
