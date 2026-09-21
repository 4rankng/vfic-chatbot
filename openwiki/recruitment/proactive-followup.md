---
type: wiki
title: "Proactive follow-up cadence and policy"
description: "FollowupRulesPolicy by lead score, cadence hours (10h/22h/46h), 3-cap, 48h-Zalo-safe margin, Vietnamese opt-out phrase matching, scheduler tick."
tags: [proactive, followup, lead-score, zalo-48h, scheduler, followup-worker]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
sources:
  - id: openwiki-source-55002f5b1d39cf35fd6d60e2
    resource: repo://backend/app/main.py
  - id: openwiki-source-d8298ce2e49ec758107bef0b
    resource: repo://backend/app/models/conversation.py
  - id: openwiki-source-bdcf12ddf74fb70beac3be12
    resource: repo://backend/app/recruitment/domain/proactive_policy.py
  - id: openwiki-source-994ed6c69158d99dc88d9838
    resource: repo://backend/app/recruitment/domain/proactive.py
  - id: openwiki-source-06ff0d3fa36993feeb388926
    resource: repo://backend/app/workers/followup_worker.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

# Proactive follow-up cadence and policy

Proactive follow-up is the bot's way of re-engaging candidates who went quiet.
A scheduler tick scans eligible conversations and enqueues per-lead jobs that
run the proactive turn — a bot message nudging the candidate to continue.

## Policy constants (`backend/app/recruitment/domain/proactive_policy.py`)

| Constant | Value | Purpose |
|---|---|---|
| `PROACTIVE_FOLLOWUP_CAP` | 3 | Max follow-ups per lead |
| `PROACTIVE_SILENCE_LIMIT` | 2 | Max consecutive silent follow-ups before stopping |
| `PROACTIVE_TICK_INTERVAL_SECONDS` | 1800 (30 min) | Scheduler tick cadence |
| `PROACTIVE_PER_TICK_CAP` | 5 | Max jobs enqueued per tick |
| `PROACTIVE_48H_WINDOW_SECONDS` | 169200 (47h) | Safety margin for Zalo's 48h rule |
| `PROACTIVE_RETRY_COOLDOWN_SECONDS` | 21600 (6h) | Min time between retries |
| `PROACTIVE_JOB_MAX_AGE_SECONDS` | 3300 (55 min) | Stale job drop threshold |
| `PROACTIVE_OPTOUT_PHRASES` | 12 Vietnamese phrases | Opt-out detection |

### The 47h safety margin

Zalo's messaging policy requires that outbound messages be sent within 48 hours
of the candidate's last inbound message. `PROACTIVE_48H_WINDOW_SECONDS` is set
to 169200 seconds (47 hours), not 48 hours, to provide a 1-hour safety margin
that accounts for clock drift, queue delays, and the time between eligibility
check and actual send.

## Per-score rules (`FollowupRulesPolicy`)

The policy defines different cadences per lead score:

| Score | Cadence hours | Eligible stages |
|---|---|---|
| `hot` | 10h, 22h, 46h | `NEW` |
| `warm` | 22h, 46h | `NEW` |
| `not_interested` | 46h | `NEW` |

Each entry in `cadence_hours` is the delay *after the candidate's last inbound
message* for that follow-up attempt. The `followup_count` indexes into the
tuple — so a `hot` lead gets its first nudge at 10h, second at 22h, third at
46h.

### Eligibility (`followup_rule_allows`)

A candidate is eligible for a proactive nudge when ALL of:
1. `lead_score` matches a rule (`hot`/`warm`/`not_interested`)
2. Rule is `enabled`
3. `lead_stage` is in `eligible_stages` (default: `NEW`)
4. `followup_count < len(cadence_hours)` — sequence not exhausted
5. `followup_count < PROACTIVE_FOLLOWUP_CAP` — global cap not reached
6. `now >= last_inbound_at + cadence_hours[followup_count]` — due time passed

Returns `(True, "due")` or `(False, reason)` where reason is one of:
`no_score_rule`, `rule_disabled`, `stage_not_eligible`,
`rule_sequence_exhausted`, `cap_reached`, `not_due`.

## Opt-out detection

`PROACTIVE_OPTOUT_PHRASES` is a tuple of 12 Vietnamese phrases (lowercased,
stripped) that signal the candidate does not want further contact:

*dừng, đừng nhắn, ko quan tâm, không quan tâm, stop, unsubscribe, để yên,
bận rồi, đừng làm phiền, không cần nữa, tôi không thích, không thích*

The proactive turn checks the candidate's last message against this list
before sending. A match sets `followup_opted_out = True` on the conversation,
which permanently excludes it from future ticks.

## Tick lifecycle (`followup_worker.py`)

### Scheduler tick (`run_proactive_followup_tick`)

1. Registered via `register_unique_tick` in `main.py` lifespan at
   `PROACTIVE_TICK_INTERVAL_SECONDS` (30 min)
2. `_run_tick_async()` opens a `worker_session` and calls
   `find_eligible_conversations(db)` — the repository scans conversations
   matching the eligibility criteria
3. For each eligible conversation, calls `enqueue_followup(conv_id)` which
   enqueues onto the `followup` RQ queue with a deterministic job structure

### Per-lead job (`run_followup_job`)

1. **Stale job guard**: if `enqueued_at` is older than
   `PROACTIVE_JOB_MAX_AGE_SECONDS` (55 min), the job is dropped silently.
   This handles the case where the worker was down and jobs backlogged.
2. Opens a `worker_session`, fetches the conversation
3. Builds `GraphDeps` via `build_deps(db)`
4. **Installation gate**: resolves the runtime policy; if the installation
   does not enable recruitment outreach (`pack_key != "recruitment"`), the
   job is skipped
5. Calls `run_proactive_turn(conv, deps)` — the graph module runs the
   proactive bot turn with the recruitment prompt

### Worker topology

- `worker-followup` × 1 replica, isolated on the `followup` queue
- The `scheduler` container (`rqscheduler`) periodically enqueues the tick
  job; the worker consumes it and fans out per-lead jobs

## Integration with conversation state

Proactive follow-up interacts with the conversation model:
- `conversation.followup_count` — incremented on each proactive attempt
- `conversation.last_followup_at` — updated on each attempt
- `conversation.followup_opted_out` — set `True` on opt-out phrase match
- `conversation.next_action_at` — set by the proactive policy to schedule
  the next eligible follow-up time

The reconcile sweep (`reconcile_worker`) does not interfere with proactive
follow-ups — it only recovers stuck *reactive* turns.
