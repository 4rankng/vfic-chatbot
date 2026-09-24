---
id: SEC-08
title: "JWT validation omits audience/issuer and required claims; algorithm is env-controlled"
severity: medium
area: security
labels: [security]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# SEC-08 — JWT validation omits audience/issuer and required claims; algorithm is env-controlled

**Severity:** medium · **Area:** security · **Effort:** S · **Labels:** security

**Trạng thái:** QA_TESTED

## Problem

Decode passes no `audience`, no `issuer`, and no `options={"require": [...]}`, and `jwt_algorithm` is an unvalidated environment string.

## Evidence

- `backend/app/core/security.py:65-72` — `jwt.decode(token, secret, algorithms=[_settings.jwt_algorithm])`.
- `backend/app/core/config.py` — `jwt_algorithm: str = "HS256"` with no `field_validator`.
- Not exploitable today: `type`/`ver`/`disabled` are checked and the subject must parse as a UUID, and `alg: none` is unreachable because PyJWT rejects a non-`None` key.

## Impact

Real exposure is misconfiguration and cross-boundary reuse: a smuggled algorithm value (e.g. `RS256`) silently breaks signing and turns logins into 500s with no boot-time guard, and if any sibling service is ever pointed at the same secret, tokens become interchangeable across trust boundaries. Note `jwt_secret` also serves as the integration-settings cipher-key fallback (`backend/app/services/integration_settings.py:299`) — a key-reuse smell.

## Suggested fix

Add `aud`/`iss` on issue and require them on decode; add `options={"require": ["exp", "sub", "type", "ver"]}`; add a `field_validator("jwt_algorithm")` allowlisting HS256/384/512 so a bad value fails at boot. Derive the cipher key from a labeled input (e.g. `sha256("secret-store-v1:" + key)`) instead of reusing `jwt_secret`.

## Evidence log

- 97db619e — iss/aud minted and verified, required claims, algorithm allowlist at boot
- tests/test_security.py
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
