---
title: Recruiter attention dashboard
date: 2026-07-12
status: approved-for-planning
mode: brainstorm
---

# Recruiter Attention Dashboard

## Summary

Design the dashboard as a shared-policy operational queue for equal-permission recruiters.
Its only job: answer **who needs attention now, why, and what action comes next**. Prefer
explainable task queues over reporting charts or recruiter performance metrics. Preserve
the current ownership boundary: each recruiter sees own + unassigned records under the
same rules; this design does not expose another recruiter's assigned records.

## Problem-First Analysis

### Solution-jumping diagnosis

The initial request asked which metrics to add. The underlying signal is not missing
analytics; recruiters lack a single prioritized view of candidate work requiring action.

### Underlying problem

Recruiters must inspect conversations, leads, and follow-ups separately to discover urgent
work. This increases response delay, risks missed follow-ups, and makes failed deliveries
look completed.

### Assumptions and validation

| Assumption | Risk if wrong | Validation |
|---|---|---|
| All recruiters use the same policy | Inconsistent prioritization | Preserve identical rules while respecting current ownership scope |
| Fast response matters most | Dashboard overweights chat | Measure age of unanswered inbound messages |
| Existing flags identify urgency | False or noisy queue | Sample `needs_human`, inbound/outbound timestamps, follow-ups |
| Recruiters will act from the dashboard | Dashboard becomes passive | Track queue-row opens and time-to-action |

### Problem statement

Equal-permission recruiters need one shared, explainable work queue because actionable
signals are split across conversations and leads. Success means urgent candidates are
identified and opened in one action, overdue work declines, and no metric exists without a
drill-down to the affected candidates.

### Alternative framings

1. **Operational triage:** prioritize immediate candidate actions. Selected.
2. **Personal performance:** show recruiter output and conversion. Rejected; permissions and
   goal do not distinguish recruiters, and ranking distracts from candidate response.
3. **Management reporting:** show funnel and system health. Rejected for the recruiter home;
   belongs on reporting/performance surfaces.

### Evidence status

**Medium.** Product direction is explicit and the code already models attention,
follow-ups, unread messages, lead stages, and delivery state. Actual queue thresholds and
false-positive rates still need production-data validation.

### Validation plan

- Inspect one week of unanswered inbound, escalation, follow-up, and delivery-failure data.
- Confirm recruiters agree with the top 20 items produced by the proposed priority rules.
- Prototype with real read-only data; measure row opens and time from inbound to response.
- Kill or revise any queue whose items recruiters routinely dismiss without action.

### Stakeholder message

We are treating the dashboard as a shared action queue, not an analytics report. Every
number must open the candidates behind it, and every row must explain why action is needed.

## Requirements

### Expected output

A responsive recruiter dashboard specification containing clickable urgency counters, an
immediate-attention queue, and a due-today queue backed by real application data.

### Acceptance criteria

- Every displayed count opens its exact candidate list.
- Every queue row shows candidate, context, reason, urgency, and one primary next action.
- Shared deterministic priority rules; no recruiter-specific ranking or RBAC variation.
- Preserve current record scope: own + unassigned for recruiters; global for admin.
- Automatic data refresh; no manual refresh button.
- Existing reporting, bot health, and infrastructure metrics stay off the recruiter home.

### Scope

**In:** recruiter action signals, queue ordering, row information, drill-down behavior,
loading/empty/partial-error states, desktop/mobile hierarchy.

**Out:** recruiter scorecards, management funnel reporting, bot/worker health, permission
changes, AI-generated priority scoring, and implementation in this brainstorm.

### Constraints and touchpoints

- React 19, React Admin, TanStack Query, Vietnamese UI.
- Preserve real API usage, shared recruiter permissions, and existing route contracts.
- Likely frontend touchpoints: `RecruitingCommandCenter.tsx`, `dashboard.css`, dashboard
  tests, and possibly `useDashboardStats.ts` after confirming it is retained.
- Likely backend touchpoints: dashboard service/repository/schema only if current list APIs
  cannot provide exact counts and filters. Any API/schema change requires human approval.

## Evaluated Approaches

| Approach | Benefits | Costs | Decision |
|---|---|---|---|
| Shared action queue | Directly reduces missed/late work; explainable | Requires precise urgency rules | **Selected** |
| KPI-first dashboard | Compact management overview | Passive, weak next actions, metric clutter | Reject for home |
| Hybrid action + analytics | Covers more stakeholders | Dilutes hierarchy; duplicates performance page | Defer |

## Approved Information Architecture

### Clickable urgency counters

Limit the top strip to five counters:

1. **Cần phản hồi** — candidate latest inbound is newer than latest outbound.
2. **Quá hạn** — reply or scheduled follow-up exceeded its target.
3. **Theo dõi hôm nay** — follow-ups due today.
4. **Ứng viên ưu tiên** — hot or registered candidates with no clear next action.
5. **Chưa đọc** — conversations with unread inbound messages.

### Immediate-attention queue

Order by deterministic severity, then oldest waiting time:

1. Failed or ambiguous outbound delivery requiring review.
2. Explicit human escalation (`needs_human`).
3. Candidate waiting beyond response target.
4. Overdue scheduled follow-up.
5. Candidate waiting within response target.
6. Hot or registered candidate without a next action.

### Due-today queue

- Follow-ups due today.
- Unread inbound messages not already in immediate attention.
- Active candidates stalled beyond the agreed inactivity threshold.
- Missing qualification information when an actionable prompt can collect it.
- Recruiter-taken-over conversations with no subsequent action.

Deduplicate across queues: a candidate appears only in the highest-priority applicable
section.

### Action-row contract

Each row shows:

- candidate name or recognizable fallback;
- recruitment project/job;
- current lead stage;
- latest message preview;
- explicit attention reason;
- waiting/overdue duration;
- phone when available;
- primary action: **Mở hội thoại**;
- optional contextual action: call or schedule follow-up.

Rows must never rely on color alone to communicate urgency.

## Priority Model

Use transparent rule-based priority. Do not introduce an opaque AI score. Recruiters must
be able to answer why an item is above another item. Approved initial thresholds:

- unanswered candidate becomes overdue after 30 minutes;
- hot or `REGISTERED` candidate needs action when no follow-up is scheduled and no
  recruiter response occurred within 24 hours (`REGISTERED` is the current model's
  qualified-equivalent; no `QUALIFIED` enum exists);
- active candidate becomes stalled after 48 hours without activity;
- failed or ambiguous delivery is review-only, with no direct resend action.

## Metrics Explicitly Excluded from Recruiter Home

- Total leads and generic contact counts.
- Hiring/conversion rate and funnel charts.
- Recruiter rankings or personal scorecards.
- Bot latency, suppression, errors, worker queue, and knowledge-ingestion health.

The current `Tên và số điện thoại` panel is not actionable by itself. Replace it with the
due/overdue work queue instead of expanding it.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Shared queue causes duplicate work | Preserve existing takeover/state cues; refresh after action |
| Too many signals create noise | Two queues, five counters, deduplication, production sampling |
| Incorrect SLA labels candidates overdue | Make threshold explicit and validate before launch |
| Client-side aggregation undercounts | Use server aggregate/list endpoints for exact totals |
| Failed delivery action could resend duplicates | Review state and existing safe resend rules before exposing action |

## Success Measures

- Lower median and p90 candidate waiting time.
- Fewer overdue follow-ups.
- Lower count of unattended human escalations.
- High percentage of dashboard opens leading to a candidate action.
- Low dismissal rate for surfaced attention items.
- No manual refresh interaction and no dashboard-only count discrepancies.

## Planning Verification Items

1. Verify whether failed/ambiguous delivery is already exposed safely to recruiters.
2. Determine which counters can use the existing `/api/v1/dashboard/metrics` response
   versus new server-side filtered counts.
3. Confirm how a scheduled future follow-up is represented by current follow-up records.

## Next Step

Create a standard implementation plan after confirming the unresolved product thresholds.
Use TDD only for extracted priority/deduplication rules or public API changes; visual
composition itself fits the default planning workflow.
