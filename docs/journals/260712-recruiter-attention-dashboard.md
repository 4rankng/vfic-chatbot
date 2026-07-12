---
title: "Recruiter attention dashboard direction"
date: "2026-07-12"
status: approved
scope: "Recruiter dashboard product direction"
---

# Recruiter attention dashboard direction

## Context

The dashboard discussion began as a request for additional metrics. Reviewing the recruiter
workflow reframed the problem: actionable candidate signals are scattered across conversations,
leads, follow-ups, and delivery state, so recruiters lack one reliable view of who needs attention
now and what to do next.

## What happened

The brainstorm approved a shared operational queue for equal-permission recruiters. The proposed
home prioritizes five clickable urgency counters, an immediate-attention queue, and a due-today
queue. Items use deterministic severity and waiting time, explain why they were surfaced, open the
affected candidate in one action, and are deduplicated across sections.

KPI-first and hybrid analytics approaches were rejected for the recruiter home. Recruiter
scorecards, funnel reporting, and bot or worker health remain on their existing reporting and
operations surfaces.

## Reflection

The useful design move was separating an operational decision surface from a reporting surface.
A compact chart may describe workload, but it does not reduce missed replies or overdue follow-ups.
The queue will only earn trust if its rules are transparent, its counts match the underlying lists,
and production samples confirm that surfaced items genuinely require action.

## Decisions

- Use shared rule-based priority, not recruiter-specific ranking or an opaque AI score.
- Make every count drill down to its exact candidate list and every row state its attention reason.
- Deduplicate candidates into their highest-priority applicable queue.
- Refresh automatically and design for desktop and mobile without relying on color alone.
- Validate exact totals server-side when existing list APIs cannot support reliable aggregation.

## Next

Before implementation planning, confirm the response target, stalled-candidate threshold,
definition of a priority candidate without a next action, safe handling of failed or ambiguous
delivery, and which counts existing APIs can provide. Then sample one week of production data and
review the proposed top items with recruiters before finalizing priority rules.

No product code, API contract, schema, migration, or user-facing dashboard was implemented as part
of this brainstorm or journal entry.

## Planning outcome

The approved direction was translated into the three-phase implementation plan at
`plans/260712-1502-recruiter-attention-dashboard/plan.md`: define a typed, read-only attention
contract; build the action-first recruiter dashboard; then verify the scoped workflow, responsive
behavior, accessibility, and documentation with reproducible evidence.

The plan resolves the open thresholds at 30 minutes for an overdue reply, 24 hours for a hot or
`REGISTERED` candidate without recruiter action or a future follow-up, and 48 hours for an active
candidate to become stalled. Failed or ambiguous latest outbound delivery remains review-only,
with no direct resend. Exact counts and bounded, deduplicated queues belong on the server; the
frontend presents and filters the returned preview without reimplementing eligibility rules.

The existing viewer boundary is deliberately preserved: recruiters see records assigned to
themselves plus unassigned records, while admins retain global scope. Equal recruiter permissions
mean shared attention rules, not visibility into another recruiter's assigned candidates.

Implementation is blocked by `plans/260710-1322-frontend-ui-ux-redesign/plan.md` so the dashboard
structure and visual baseline settle first. The additive endpoint and response schema also require
explicit human approval before implementation. No implementation, API change, migration,
verification run, or deployment occurred during planning.

## Planning reflection and next step

Keeping one backend read model as the authority makes the counters explainable and prevents
client-side caps from silently undercounting work. The phased plan also keeps the change
reversible: it adds no persistence, dependency, ownership policy, or outbound mutation.

Next, complete the blocking UI/UX plan, obtain approval for the additive public contract, validate
the proposed rules against representative recruiter data, and then execute the three phases with
the focused quality gates recorded in the plan.
