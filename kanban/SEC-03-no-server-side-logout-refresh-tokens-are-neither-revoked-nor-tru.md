---
id: SEC-03
title: "No server-side logout; refresh tokens are neither revoked nor truly rotated"
severity: high
area: security
labels: [security]
effort: M
status: todo
found: 2026-09-24
---

# SEC-03 — No server-side logout; refresh tokens are neither revoked nor truly rotated

**Severity:** high · **Area:** security · **Effort:** M · **Labels:** security

## Problem

There is no `/auth/logout`. `POST /auth/refresh` re-issues a token pair without invalidating the token it consumed, so a stolen 14-day refresh token survives the victim's logout and is indistinguishable from legitimate rotation.

## Evidence

- `backend/app/api/auth.py` — the whole auth surface is login / forgot-password / reset-password / refresh / me / change-password; no logout route.
- `backend/app/identity/infrastructure/http.py:65-86` — refresh validates `type`/`user`/`disabled`/`ver`, then mints new tokens; the presented token is never invalidated. No jti or generation store exists anywhere in `app/`.
- `backend/app/core/config.py:92-93` — access token 60 min, refresh token 14 days.
- Frontend logout only clears `localStorage` (`frontend/src/components/atomic-crm/providers/rest/authProvider.ts`).

## Impact

An exfiltrated refresh token grants access for up to 14 days; logout is cosmetic; the theft is undetectable from token traffic. Compounded by the absence of CSP with JWTs in `localStorage` (SEC-06).

## Suggested fix

Add `POST /api/v1/auth/logout` that bumps `user.token_version` — both token types already carry and check `ver` (`backend/app/identity/application/authentication.py:36-37`, `identity/infrastructure/http.py:83-84`), making this the cheapest correct fix. For real rotation, store a per-user refresh generation and reject a stale one so a replay invalidates the family. Also bump `token_version` on email change (`backend/app/services/user_service.py:139-148`).

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
