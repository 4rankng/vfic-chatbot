---
id: FE-14
title: "Duplicated credential-field machinery between the Zalo and Facebook pages"
severity: medium
area: frontend
labels: [tech-debt]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# FE-14 — Duplicated credential-field machinery between the Zalo and Facebook pages

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** QA_TESTED

## Problem

Two masked-secret-with-reveal implementations exist — `CredentialSecretField` for Zalo (copy + reveal + status) and an inline `MetaAppSecretField` for Facebook (reveal only, `readOnly` when revealed, different placeholder semantics) — and the two pages disagree on the data-access idiom for the same kind of screen. Every credential-policy change must be made twice, and one of the two has no test for copy/reveal parity.

## Evidence

- `frontend/src/components/atomic-crm/integrations/CredentialSecretField.tsx:28-103` — the Zalo masked-secret field with copy, reveal and status.
- `frontend/src/components/atomic-crm/integrations/FacebookMessengerIntegrationPage.tsx:110-190` — `MetaAppSecretField` (reveal only, `readOnly` when revealed) and `:80-107` `MetaAppPlainField` for non-secret fields; both share `SettingsFieldStatus` but neither reuses the other's field shell.
- Idiom mismatch: Facebook uses `useQuery` at `:223`, `:245`, `:352`, `useGetList` at `:230` and `useMutation` at `:251`/`:361`/`:375` with `invalidateQueries` at `:265`/`:386`; Zalo uses `zaloIntegrationGateway` + `useState` with a manual reload (`integrations/ZaloIntegrationPage.tsx:1014-1063`).
- OAuth callback handling is factored out correctly (`integrations/facebook-oauth-callback.ts`, imported at `FacebookMessengerIntegrationPage.tsx:36`) — a good precedent for the rest of the extraction.

## Impact

Every credential-policy change (masking rules, reveal-on-demand, "blank means keep", clipboard behaviour) must be made in two places, and one of the two has no test for copy/reveal parity.

## Suggested fix

Generalise `CredentialSecretField` into an `admin/`-level `SecretField` + `PlainField` pair with a `reveal?: () => Promise<string | null>` prop, delete `MetaAppSecretField` and `MetaAppPlainField`, and move the Zalo page's load/save/test onto TanStack Query using the key conventions Facebook already uses.

## Evidence log

- decb8b63 — one `SecretField` + `PlainField` pair over a shared `FieldShell` replaces `CredentialSecretField` and the inline `MetaAppSecretField`/`MetaAppPlainField`. The two pages' real differences became props: supplying `notify` adds the copy action (Zalo), supplying `reveal` makes the eye fetch the stored secret and render read-only while revealed (Facebook).
- The Zalo page's load/save/test moved onto TanStack Query with the same key conventions the Facebook page already used. `FacebookMessengerIntegrationPage` 794 → 676 LOC.
- Verified: `CredentialSecretField.test.tsx` moved to `presentation/SecretField.test.tsx` with assertions preserved and extended; integrations suite 48 tests pass.
- QA 2026-09-24 (orchestrator, first-hand): unit lane 2299 passed + ruff clean; integration lane 130 passed on a disposable Postgres 16 at alembic head; frontend tsc, eslint and vitest 593 all green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
