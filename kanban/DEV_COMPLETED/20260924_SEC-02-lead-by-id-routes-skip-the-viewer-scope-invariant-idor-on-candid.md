---
id: SEC-02
title: "Lead by-id routes skip the viewer-scope invariant (IDOR on candidate PII)"
severity: high
area: security
labels: [security, reliability]
effort: M
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# SEC-02 — Lead by-id routes skip the viewer-scope invariant (IDOR on candidate PII)

**Severity:** high · **Area:** security · **Effort:** M · **Labels:** security, reliability

**Trạng thái:** DEV_COMPLETED

## Problem

`GET/PATCH /leads/{id}` and every lead sub-resource load the row by primary key with no ownership predicate, so any authenticated recruiter can read and mutate every other recruiter's candidate PII. The list/board queries and the conversation detail path both enforce the invariant; the lead by-id path does not, which makes this an omission rather than a deliberate org-wide policy.

## Evidence

- `backend/app/api/leads.py:47-57` — `_load(lead_id, db)` takes no viewer.
- `backend/app/services/lead/service.py:52-58` — `get()` is a plain `db.get(Lead, lead_id)`; `update`/`assign`/`set_stage` apply no ownership check.
- `backend/app/services/lead/service.py:75` — list *does* apply `viewer_scope_filter(...)`; `backend/app/services/conversation/repository.py:156-162` scopes conversation detail the same way.
- `backend/app/api/leads.py:40-44` — the route gate is `require_capability_or_legacy("candidate_intake")`, an installation capability, not a role.
- `backend/app/schemas/lead.py:18-35` — `LeadOut` exposes name, phone, address, notes.
- Related: `backend/app/api/bot_runs.py:32-42,45-60` is org-wide for both roles and its projection can echo `proposed_reply` for conversations the caller cannot open.

## Impact

Sequential integer ids make enumeration trivial: full candidate PII for the whole tenant, `/assist` chatops content derived from another recruiter's conversation, and `POST /{id}/assign {"recruiter_id": "<self>"}` to steal any lead.

## Suggested fix

Thread the viewer through the lead read path as conversations do: add `LeadRepository.get_visible` mirroring `viewer_can_access_lead` (`backend/app/services/viewer_scope.py:70-77`), return **404** rather than 403 so ids are not probeable, and apply it to every by-id route plus `LeadService.update/assign/set_stage/create_followup/replace_manual_tags`. Validate `AssignRequest.recruiter_id` resolves to an enabled user. Scope the `/bot_runs` projection or drop `proposed_reply` from the list response.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
