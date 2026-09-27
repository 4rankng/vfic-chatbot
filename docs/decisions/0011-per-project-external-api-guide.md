# ADR-0011: Per-project external API integration driven by an admin-written guide

- **Status:** Superseded by ADR-0012. The employee password-reset flow this ADR was written for
  turned out to be deployment-wide (the TingTing app API), so it moved to a global integration
  with an embedded guide. The per-project mechanism was then removed at the product owner's
  direction (settings panel deleted, then the endpoints/service/tool and its prompt injection) —
  no project-scoped external API remains. `projects.external_api` survives as an unread column
  because dropping it would be a destructive migration.
- **Date:** 2026-09-26
- **Decider:** Product owner / operator

## Context

Candidates and employees reported never receiving the password-reset OTP, and the bot could only
apologise and hand off to a human. The employer's HR system exposes an integration API — a
four-step flow (`employee/lookup` → `password-reset/otp` → `password-reset/verify` →
`password-reset/reset`) authenticated with an `X-API-Key` header — and the operator wants the bot to
run it and answer truthfully from the real response.

Two shapes were possible. A vendor-specific code path would bake one employer's API into the graph
layer, which the architecture forbids. A generic per-project integration configured by an admin
needs a way to tell the model what it may call: an itemized per-endpoint allowlist, or the vendor's
own integration document as the specification.

The operator chose the guide. Duplicating the vendor's already-complete document into endpoint rows
would double the maintenance and drift the moment the vendor changes; the vendor's own authorization
(`reset` requires a `reset_token` minted only after the employee proves possession of the OTP) is the
authority for the mutating steps, so a second, hand-maintained write gate bought little.

## Decision

One nullable JSONB column, `projects.external_api` (migration `0056_project_external_api`), holds
`enabled`, `base_url`, `auth_header`, `auth_scheme`, the sealed API key, and a free-text `guide`
(≤ 16 000 characters). The key is sealed with the existing AES-GCM cipher bound to the
project-scoped AEAD context `project-external-api:<project id>`, so a row copied to another project
cannot be decrypted.

Admin-only routes `GET`/`PUT /api/v1/knowledge/projects/{id}/external-api` read and replace it. The
key is write-only in both directions: the read surface returns only `{configured, preview:"<n> ký
tự"}`, and no field for the integration is added to `ProjectOut`/`ProjectUpdate`.

A new agent tool, `call_project_api(method, path, params)`, resolves the project (a focused
conversation's slug → the only enabled project → `ambiguous`, which makes the tool ask the candidate
→ `not_configured`) and then issues exactly one request. The enforced boundary is the **fixed
origin**:

- `base_url` is validated when saved (`https`, or `http` for a loopback host; no userinfo, query or
  fragment) and re-validated when read; it never enters the prompt.
- The model supplies only a relative path, which must start with `/` and must not contain `://`,
  `//`, `..`, `?` or `#` — an absolute URL is refused before a request is built.
- Method is limited to `GET`/`POST`; params are a flat `str → str` map, at most 10 entries of 200
  characters, and are never interpolated into the path.
- Timeout 8 s; the response body is truncated to 4 000 characters; a status ≥ 400 returns **no**
  body (an error envelope can echo the submitted parameters).
- Non-GET calls consume two Redis buckets — an identical-params 60 s dedupe window and a 60/60 s
  per-(project, method, path) ceiling — and fail open when Redis is unavailable, matching
  `app.core.ratelimit`.
- Logging carries project id, method, path, status and elapsed only; never the key, a parameter
  value, or a body.

The guide reaches the model as an `=== API NGOÀI CỦA DỰ ÁN ===` block appended to the system prompt
of a **FOCUSED** turn (one indexed read per turn, no cache, so an admin edit takes effect on the next
turn).

## Consequences

- No vendor-specific code path exists; adding a second employer's API is an admin task, not a deploy.
- The tool rides the `knowledge` capability in `app/graph/runtime_policy.py`. That map is not part of
  `pack_contract_hash` (only `CapabilityDefinition` metadata is), so no installed revision is
  stranded and no revision re-pin is needed. A new capability id would have bumped
  `recruitment_v1_contract.json` and left the tool unreachable until an operator re-pinned.
- Cost: a focused conversation for a configured project pays the guide's tokens on every turn. The
  16 000-character cap is therefore also the per-turn token budget the admin is choosing, and the
  panel shows the character count live.
- Accepted risk: there is no per-endpoint write gate. A `POST` described in the guide is callable
  whenever the project integration is enabled. The compensating controls are the fixed origin, the
  method/param limits, and the 60 s mutate window.
- The feature is inert by default: `enabled` false, no row, or an undecryptable key all resolve to
  the pre-existing behaviour (no prompt block, the tool reports `not_configured`, the bot keeps its
  human handoff).
- Explicitly out of scope: global/cross-project configuration, OAuth flows, request retries, inbound
  webhooks, and per-candidate credentials.
