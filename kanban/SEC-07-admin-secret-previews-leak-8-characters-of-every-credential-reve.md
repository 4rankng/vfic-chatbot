---
id: SEC-07
title: "Admin secret previews leak 8 characters of every credential; reveal endpoint has no step-up"
severity: medium
area: security
labels: [security]
effort: S
status: todo
found: 2026-09-24
---

# SEC-07 — Admin secret previews leak 8 characters of every credential; reveal endpoint has no step-up

**Severity:** medium · **Area:** security · **Effort:** S · **Labels:** security

## Problem

Every stored integration secret is returned to admin GETs as `first4...last4`, and the Facebook reveal endpoint returns the Meta app secret in plaintext with no re-authentication.

## Evidence

- `backend/app/services/integration_settings.py:350-366` — `_preview()` returns `f"{value[:4]}...{value[-4:]}"`; attached at `:465-473`, `:501`, `:540`, `:591`, `:629`, `:1099-1104`.
- `backend/app/api/integrations.py:1116-1145` — `POST /admin/integrations/facebook/credentials/reveal` returns `facebook_app_secret` and the webhook verify token in plaintext; `require_admin` + `no-store` + actor logged, but no step-up.

## Impact

Eight characters of every credential narrow brute force, and the Meta app secret is the HMAC key that authenticates every Facebook webhook — possessing it converts to forging inbound Messenger events. Any live admin session can retrieve it.

## Suggested fix

Replace character previews with a `configured: true` / length-only status for authorizing secrets, keeping `_preview` only for non-authorizing identifiers. Require password re-entry or a short-lived single-use token on the reveal endpoint and audit-log the reveal.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
