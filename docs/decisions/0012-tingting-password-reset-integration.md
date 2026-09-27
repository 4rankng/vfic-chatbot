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
   `https://tingting.vip` — origin only, since the `/api/v1` prefix is part of the guide's paths)
   with a validated operator override on
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

8. **The reset flow is step tools with server-side state, not raw endpoints.** The
   first cut let the model drive `call_tingting_api` for all four endpoints, which
   cannot work across turns: an agent turn's message list does not carry the
   previous turn's tool results, so the `session_id` from the OTP turn was gone
   when the employee replied with the code — production sent
   `password-reset/verify` with a stale session and got HTTP 400, and a "resend the
   OTP" minted a new session while the model held the old one ("phiên đã hết hiệu
   lực" although the code had just arrived). The steps are therefore
   `verify_tingting_identity` / `send_tingting_otp` / `confirm_tingting_otp` /
   `reset_tingting_password`, with `session_id` and `reset_token` held by
   `TingtingFlowStore` under the employee's phone digest (Redis, 15 min, merged per
   step). `call_tingting_api` stays bound for the read-only lookup only and refuses
   mutating paths.
9. **Identity is decided in code.** The guide's prose comparison looped: the model
   re-asked for a field the employee had already given, rejected an unaccented name
   (`Nguyen Viet Dung` vs `Nguyễn Việt Dũng`), and could not tell a phone re-entered
   in the CCCD slot from a CCCD. Matching now folds diacritics/case/spacing on
   names, folds `+84` on digits and compares the CCCD as digits; a record with no
   CCCD, or a CCCD equal to its own mobile, drops the CCCD requirement instead of
   deadlocking on a field that can never match. A verified phone is recorded and is
   the gate `send_tingting_otp` reads.
11. **The reset sets a memorable one-time password.** Letting the app generate one produced
    strings an employee cannot retype from a Zalo bubble (`PN&&mf6P73x4`), so the tool sets its
    own `Matkhau@482913`-style password (word + symbol + 6 digits: upper, lower, digit and symbol
    so a policy accepts it) and tells the employee to change it after the first login. A 400
    from the app falls back to the app's own generator rather than failing the reset.
10. **A follow-up mid-flow stays on the flow.** `TurnDecisions.recent_account_support`
    (judged from the assistant's last message, newly supplied as `bot_last_message`)
    re-routes a short reply — "sao rồi", "ok", a bare phone number — to
    `employee_support` with reason `employee_support_continuation`; without it a
    progress nudge classified as small talk, lost the tools and answered "vẫn đang
    chờ". The progressive-bubble contact guard also now grades against the history
    the model was actually shown, not the current message alone.

## Consequences

- The admin configures one key; rotating it takes effect on the next turn (no
  cache on the configuration read).
- Adding a second employee-facing integration means adding another settings group
  + an embedded guide, not another per-project panel.
- The reset flow survives whatever the model forgets: the verified phone, the OTP
  session and the reset token live in Redis, and the model owns only the phone, the
  6-digit code and an optional new password.
- ADR-0011's per-project integration remains for **project-specific** systems; it
  keeps its FOCUSED-only prompt injection and gained an `api_key_missing`
  readiness blocker so an enabled-without-key row cannot report "ready".
- The knowledge capability gains `call_tingting_api`. The capability→tool map is
  not part of `pack_contract_hash`, so installed revisions need no re-pin.
