---
id: TEST-06
title: "No dependency or security scanning in CI"
severity: high
area: testing
labels: [testing, security, ops]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# TEST-06 — No dependency or security scanning in CI

**Severity:** high · **Area:** testing · **Effort:** S · **Labels:** testing, security, ops

**Trạng thái:** QA_TESTED

## Problem

The repository has two workflows, no Dependabot config, and no `pip-audit`, `npm audit`, CodeQL or SAST step anywhere, so a published CVE in any pinned dependency is invisible until exploited. The team already patches transitive CVEs by hand via `overrides`, with no automation to keep doing it.

## Evidence

- Only two workflows exist — `.github/workflows/quality-gates.yml` and `openwiki-update.yml` — and `.github/dependabot.yml` is missing.
- No `pip-audit`, `npm audit`, CodeQL or SAST step appears in `.github/workflows/quality-gates.yml`.
- Live attack-surface dependencies are pinned in `backend/pyproject.toml` (`pyjwt[crypto]`, `cryptography>=42`, `passlib[argon2]`, `google-genai`, `langchain-openai`) and `frontend/package.json` (`dompurify`, `socket.io-client`, `marked`, `zod`).
- `frontend/package.json` carries two `overrides` (`esbuild`, `decode-uri-component`) that are themselves hand-applied transitive-CVE patches — evidence the team cares, with no automation behind it.

## Impact

A published CVE in any pinned dependency stays invisible until exploited, on a single droplet holding candidate PII and Zalo/Facebook provider tokens.

## Suggested fix

Add `.github/dependabot.yml` for `pip` (backend) and `npm` (frontend), weekly and grouped, plus an advisory (non-blocking) `pip-audit --strict` and `npm audit --omit=dev` job. Any advisory that is deliberately accepted gets a comment rather than silence.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
