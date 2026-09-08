---
type: wiki
title: "Salary/profile recommendation logic"
description: "Salary band parsing, profile statement detection, recency/salary sort intents, and the recommendation query port used by the bot."
tags: [recommendation, salary, scoring, job-matching, lead-profile, active-jobs]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
sources:
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-91f86a8995a197f9604c8e4f
    resource: repo://backend/app/recruitment/application/ports.py
  - id: openwiki-source-23a00a9283e68584c6175a33
    resource: repo://backend/app/recruitment/domain/provider.py
  - id: openwiki-source-c7eeccf62aa70ad3ab79514b
    resource: repo://backend/app/recruitment/domain/recommendation.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

# Salary/profile recommendation logic

The recommendation engine matches candidates to active job postings using a
weighted structured scorer. It lives in `backend/app/recruitment/domain/recommendation.py`
(pure domain — no DB, no LLM) and is consumed by the bot brain through
`RecommendationQueryPort`.

## Salary band parsing (`parse_salary_band`)

Parses free-text Vietnamese salary descriptions into a `(min, max)` VND/month
band. Handles three formats:

| Pattern | Example | Result |
|---|---|---|
| *triệu* / *tr* | "8-10 triệu" | (8M, 10M) |
| *nghin* / *k* | "500k-700k" | (500K, 700K) |
| Plain 6+ digits | "8000000-10000000" | (8M, 10M) |

For single values (not a range), returns `(value * 0.8, value)` — the floor
is set to 80% of the stated amount to account for negotiation range.

Normalization uses `normalize_vietnamese_text` (diacritic-insensitive) before
regex matching.

## Salary profile statement detection (`is_salary_profile_statement`)

Returns `True` for first-person current/expected salary declarations. Matches
against 8 Vietnamese markers after diacritic normalization:

*mong muon, ky vong, expected salary, salary expectation, dang nhan luong,
dang co thu nhap, luong hien tai cua, thu nhap hien tai cua*

This is distinct from `parse_salary_band`: `is_salary_profile_statement`
detects *intent* (the candidate is stating their salary), while
`parse_salary_band` extracts *values* from any text.

## Recommendation weights (`RecommendationWeights`)

| Weight | Default | Factor |
|---|---|---|
| `title` | 0.35 | desired_job ↔ job.title overlap |
| `salary` | 0.25 | expected_salary band overlap |
| `location` | 0.20 | living_area/region ↔ province/district |
| `support` | 0.10 | accommodation/transport flag match |
| `experience` | 0.10 | years_experience fit / "no exp required" bonus |

Weights are tunable via `Settings` fields (`rec_weight_*`). The defaults are
starting points — MiniMax §7.2 notes they should be re-tuned against labeled
hires after the first 1,000 production conversations.

## Scoring functions

### `score_title`
Vietnamese diacritic-insensitive word overlap between `desired_job` and
`job.title`. Returns similarity ≥ 0.5 as a match (with reason), partial
overlap scaled by 0.5.

### `score_salary`
Compares the candidate's parsed salary band against the job's salary range.
Full fit (1.0) when `job_floor >= lead_floor`; partial fit (0.7) when
`job_ceiling >= lead_floor` but `job_floor < lead_floor`.

### `score_location`
Vietnamese diacritic-insensitive word overlap between `living_area`/`region`
and `province`/`district`. Labels: "cùng khu vực" (same area, ≥0.5) or
"gần khu vực" (nearby, <0.5).

### `score_support_flags`
Checks `wants_accommodation` ↔ `accommodation_support` and
`wants_transport` ↔ `transport_support`. Each match adds 0.5, capped at 1.0.

### `score_experience`
If the job's `experience_required` contains no-experience markers (*khong,
chua can, khong can, duoc hoc viec, moi ra truong*), returns 1.0. Otherwise
0.0 — the scorer does not penalize experience mismatches.

## `score_job` — the weighted formula

```
total = 0.35 * title + 0.25 * salary + 0.20 * location + 0.10 * support + 0.10 * experience
```

Returns a `ScoredJob` with the composite score (rounded to 3 decimals) and
concatenated reasons. Falls back to "việc làm đang tuyển" when no specific
reasons were generated.

## Active job lookup (`select_matching_active_jobs`)

Applies explicit semantic filters to a scoped active-job catalog:

| Filter | Matches against |
|---|---|
| `role` | `job.title` |
| `company` | `company_name`, `company_aliases`, `factory_name`, `project_name`, `project_slug` |
| `location` | `province`, `district`, `address` |

Company and location fields support identity-typo matching via `SequenceMatcher`
(threshold 0.86, min length 5 chars) and acronym detection (first-letter
concatenation of multi-word tokens).

Sorting options: `salary_desc`, `salary_asc`, `created_at`. Jobs with no
salary are sorted last. Returns `ActiveJobLookup` with status `matched`,
`no_match`, or `catalog_empty`.

## `LeadProfile` — candidate signals

`LeadProfile.from_lead(lead)` extracts structured signals from the lead row:
- `desired_job`, `living_area`, `region`, `expected_salary_text`
- `age`, `gender`, `years_experience_text`
- `wants_accommodation`, `wants_transport` (from conversation context)
- Parsed: `salary_min`, `salary_max` via `parse_salary_band`

`has_any_signal` returns `True` when at least one of `desired_job`,
`living_area`, `region`, or `salary_max` is present.

## Ports consumed by the bot brain

### `RecommendationQueryPort`
- `recommend_jobs_for_lead(chat_id, top_k=5, province=None)` — the main
  entry point: loads the lead, scores all active jobs, returns top-K
- `list_active_jobs(project_slug, role, company, location, top_k, sort_by)`
  — direct filtered lookup without scoring

### `LeadContextQueryPort`
- `profile_text(chat_id)` — human-readable candidate profile for the LLM
  context
- `context(chat_id, current_user_text, recent_messages)` — broader context
  including recent conversation

### `FollowupEligibilityPort`
- `allowed(conversation)` — final per-conversation recruitment follow-up
  decision (delegates to the proactive policy)

## Provider resolution (`recruitment/domain/provider.py`)

`provider_from_conversation(conversation)` resolves the canonical provider
(`zalo_bot`, `zalo_oa`, `facebook_messenger`) from the channel identity,
falling back to legacy `zalo_channel` field. `recipient_from_conversation`
returns the provider-specific recipient id (Zalo `zalo_chat_id` or Messenger
`external_id`).
