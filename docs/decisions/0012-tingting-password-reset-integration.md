# ADR-0012: Deployment-wide TingTing password-reset integration with an embedded guide

- **Status:** Accepted
- **Date:** 2026-09-26
- **Decider:** Product owner / operator

## Context

Employees who use the TingTing app ask the Zalo bot to reset a forgotten password.
The TingTing app exposes a machine channel for exactly that: four
`/api/v1/integration/*` endpoints authenticated with an `X-API-Key` header
(employee lookup by phone, send OTP, verify OTP, reset password).

ADR-0011 gave each *project* an optional external-API guide with an admin-pasted
integration document. Reusing that surface for the reset flow failed in
production for two compounding reasons:

- the guide only reached the prompt on a **FOCUSED** project turn, so an employee
  who had not selected a project never saw the endpoints; and
- the bot then classified the request as out of scope and refused — with an
  **invented** IT hotline and e-mail address, because nothing in the prompt
  forbade fabricating contact channels.

The reset flow also is not project surface at all: one deployment serves every
tenant's employees, and the workflow (lookup → verify identity → OTP → verify →
reset) is identical for all of them.

## Decision

1. The reset flow is a **deployment-wide integration**, configured in the admin
   settings console with exactly one secret: the API key (`X-API-Key`), stored
   AES-GCM-encrypted in `integration_settings` under `tingting_api_key`
   (`GET`/`PUT /api/v1/admin/integrations/tingting`, status-only responses).
2. The workflow guide is **embedded in code** (`app/graph/tingting_guide.py`):
   it is product behaviour, not per-tenant content, so the admin never pastes or
   maintains it. It is appended to the system prompt whenever a usable key is
   configured — independent of project focus.
3. The origin is fixed in code (`TINGTING_API_BASE_DEFAULT`,
   `https://tingting.vip/api/v1`) with a validated operator override on
   `Settings` (`tingting_api_base`) for dev/smoke deployments. The model supplies
   only a relative path plus the method.
4. One new tool `call_tingting_api(method, path, params)` shares the
   per-project integration's guards: relative-path validation, `GET`/`POST`
   only, flat bounded `str -> str` params, identical-params dedupe plus an
   hourly ceiling, no response body on error statuses, and exactly one outbound
   request site (`app/services/tingting_api.py`). The read-only employee lookup
   is **exempt from the dedupe bucket** (ceiling only): step 2 of the guide has
   the model re-read the record to compare the employee's identity, and a second
   identical lookup is a legitimate retry — refusing it as a duplicate stalled
   the flow in production and was reported to the employee as a false rate
   limit. A refusal now surfaces as `duplicate_request`, distinct from a genuine
   `rate_limited`.
5. **Identity is a hard precondition.** The guide requires full name + CCCD +
   mobile from the employee to match the lookup response before the OTP endpoint
   may be called.
6. A new `employee_support` intent routes such turns to this tool (never a
   refusal while the guide is present), and the agent lane keeps the API tool
   bound even on a focused RAG turn.
7. Fabricated contact channels are now guarded: a reply stating a phone number
   or e-mail absent from the turn's tool results and prompt text is replaced by
   an honest abstention (`grounding.UNVERIFIED_CONTACT_REPLY`).

## Consequences

- The admin configures one key; rotating it takes effect on the next turn (no
  cache on the configuration read).
- Adding a second employee-facing integration means adding another settings group
  + an embedded guide, not another per-project panel.
- ADR-0011's per-project integration remains for **project-specific** systems; it
  keeps its FOCUSED-only prompt injection and gained an `api_key_missing`
  readiness blocker so an enabled-without-key row cannot report "ready".
- The knowledge capability gains `call_tingting_api`. The capability→tool map is
  not part of `pack_contract_hash`, so installed revisions need no re-pin.
