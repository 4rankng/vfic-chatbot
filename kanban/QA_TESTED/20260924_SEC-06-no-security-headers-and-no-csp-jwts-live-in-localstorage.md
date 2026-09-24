---
id: SEC-06
title: "No security headers and no CSP; JWTs live in localStorage"
severity: medium
area: security
labels: [security]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# SEC-06 — No security headers and no CSP; JWTs live in localStorage

**Severity:** medium · **Area:** security · **Effort:** S · **Labels:** security

**Trạng thái:** QA_TESTED

## Problem

The application sets no HSTS / CSP / X-Frame-Options / X-Content-Type-Options / Referrer-Policy, and the only edge config that could set them is rendered on the host and absent from the repo.

## Evidence

- `backend/app/main.py:189-195` — the only middleware is `CORSMiddleware`; no `TrustedHostMiddleware`.
- `frontend/index.html` has no CSP meta; a repo-wide grep for those header names finds them only inside `.claude/skills/` reference docs.
- `backend/docker-compose.yml` (caddy service) mounts `./Caddyfile`, which `backend/scripts/flip_caddy.sh` renders at deploy time — so this could **not** be verified from the repo. Confirm on the host before treating as confirmed.
- `frontend/src/lib/apiClient.ts:12-13` — the JWT pair sits in `localStorage` under `RaStore.auth.*`.

## Impact

Any script execution is silent full account takeover, with a 60-minute access token and a 14-day refresh token that cannot be revoked (SEC-03). Without `X-Frame-Options`/`frame-ancestors` the console is also clickjackable.

## Suggested fix

Add to the deploy-rendered Caddy config: `Strict-Transport-Security`, `Content-Security-Policy: default-src 'self'; object-src 'none'; frame-ancestors 'none'` (verify whether Tailwind-injected styles need `style-src 'unsafe-inline'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`. Add `TrustedHostMiddleware` to `main.py`. Keep the declaration in the deploy template so a redeploy cannot lose it.

## Evidence log

- 1be1b2d0 + 3cabb7b4 — CSP/X-Frame-Options/Permissions-Policy on the deploy-rendered template, TrustedHostMiddleware
- tests/test_security_headers.py, tests/test_allowed_hosts_config.py
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
