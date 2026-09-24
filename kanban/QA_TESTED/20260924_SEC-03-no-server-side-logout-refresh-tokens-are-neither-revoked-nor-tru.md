---
id: SEC-03
title: "No server-side logout; refresh tokens are neither revoked nor truly rotated"
severity: high
area: security
labels: [security]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# SEC-03 — No server-side logout; refresh tokens are neither revoked nor truly rotated

**Severity:** high · **Area:** security · **Effort:** M · **Labels:** security

**Trạng thái:** QA_TESTED

## Problem

There is no `/auth/logout`. `POST /auth/refresh` re-issues a token pair without invalidating the token it consumed, so a stolen 14-day refresh token survives the victim's logout and is indistinguishable from legitimate rotation.

## Evidence

- `backend/app/api/auth.py` — the whole auth surface is login / forgot-password / reset-password / refresh / me / change-password; no logout route.
- `backend/app/identity/infrastructure/http.py:73-93` — refresh validates `type`/`user`/`disabled`/`ver`, then mints new tokens; the presented token is never invalidated. No jti or generation store exists anywhere in `app/`.
- `backend/app/core/config.py:107-108` — access token 60 min, refresh token 14 days.
- Frontend logout only clears `localStorage` (`frontend/src/components/atomic-crm/providers/rest/authProvider.ts`).

## Impact

An exfiltrated refresh token grants access for up to 14 days; logout is cosmetic; the theft is undetectable from token traffic. Compounded by the absence of CSP with JWTs in `localStorage` (SEC-06).

## Suggested fix

Add `POST /api/v1/auth/logout` that bumps `user.token_version` — both token types already carry and check `ver` (`backend/app/identity/application/authentication.py:42-43`, `backend/app/identity/infrastructure/http.py:94`), making this the cheapest correct fix. For real rotation, store a per-user refresh generation and reject a stale one so a replay invalidates the family. Also bump `token_version` on email change (`backend/app/services/user_service.py:125-126,141`).

## Evidence log

- d117e086 — POST /auth/logout bumps token_version, refresh rejects a stale ver, email change bumps it
- tests/test_auth_token_revocation.py — old refresh/access tokens die at logout, fresh login works, route contract
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
