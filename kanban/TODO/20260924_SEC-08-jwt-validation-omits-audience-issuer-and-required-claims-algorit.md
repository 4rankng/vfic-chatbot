---
id: SEC-08
title: "JWT validation omits audience/issuer and required claims; algorithm is env-controlled"
severity: medium
area: security
labels: [security]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# SEC-08 — JWT validation omits audience/issuer and required claims; algorithm is env-controlled

**Severity:** medium · **Area:** security · **Effort:** S · **Labels:** security

**Trạng thái:** TODO

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

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
