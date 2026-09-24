---
id: FE-01
title: "ZaloIntegrationPage is a 2072-LOC module whose one component owns four product domains"
severity: high
area: frontend
labels: [tech-debt]
effort: L
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# FE-01 — ZaloIntegrationPage is a 2072-LOC module whose one component owns four product domains

**Severity:** high · **Area:** frontend · **Effort:** L · **Labels:** tech-debt

**Trạng thái:** QA_TESTED

## Problem

`ZaloIntegrationPage.tsx` is 2072 LOC, of which a single component is ~1100 LOC with 19 `useState` owning four product domains: the Zalo channel form, the LLM provider descriptors, the JEV panel, and three pages embedded from other products. Load, save, dirty-check and test logic is inlined rather than extracted, and three separate save/dirty mechanisms coexist in the same file.

## Evidence

- `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:973-2072` — one component of ~1100 LOC; the module totals 2072 LOC.
- `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:978-1007` — 19 `useState` in that one function (settings, providerSettings, settingsStatusState, form, providerForm, providerEnabled, providerTesting, providerSaving, providerLastTests, llmDefaultProvider, llmFailoverOrder, activeItemId, testingBot, testingOa).
- `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:1483-1505` — `renderSettingsBody()` branches over 6 sections and mounts other products' pages: `<PersonaList embedded />` `:1487`, `<UserList embedded />` `:1495`, `<FacebookMessengerIntegrationPage />` `:1501`.
- `frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:1080-1082` — the comment explicitly acknowledges that `llmContext` identity changes on every render.
- Inlined load/save/test logic instead of hooks: `load` `:1014-1063`, `providerPayload` `:1089-1121`, `hasProviderPanelEdits` `:1123`, `saveProviderPanels` `:1127-1169`, `discardProviderPanels` `:1171-1186`, `testProviderPanel` `:1188-1236`, `handleProviderEnabledChange` `:1259-1280`.

## Impact

Any change to one integration risks the other three, because the LLM descriptor machinery and the Zalo form share state and the same render function. The whole Settings resource is one lazy chunk that must be parsed as a single unit, and the main component re-renders on every keystroke in any of ~40 fields.

## Suggested fix

Extract along the seams the audit names: `integrations/domain/providerDescriptors.ts` (move `:82-465` types and `PROVIDER_PANELS_BY_ID`), `application/useSettingsBundle.ts` (owns `load`), `application/useZaloForm.ts`, `application/useProviderPanels.ts` (owns 7 `useState` + 5 handlers — the single biggest win), `presentation/SettingsChrome.tsx`, `ZaloChannelSection.tsx`, `LlmProvidersSection.tsx` and `JevSection.tsx`, leaving a ~120-LOC shell. Move the three embedded foreign pages (`settings-agents`, `settings-users`, `settings-facebook-messenger`) to the routes that own those products.

## Evidence log

- decb8b63 — `ZaloIntegrationPage.tsx` 2072 → 98 LOC: descriptor table to `domain/providerDescriptors.ts`, state owners to `application/{useSettingsBundle,useZaloForm,useProviderPanels}.ts`, chrome/sections to `presentation/*`; the three save/dirty mechanisms collapse onto one.
- Deliberate deviation: the settings navigation is unchanged. The embedded `PersonaList`, `UserList` and `FacebookMessengerIntegrationPage` render from thin section components instead of moving to their own routes, because that would be a user-visible navigation change.
- Verified: `npx vitest --run src/components/atomic-crm/integrations` — 5 files / 48 tests pass; `npm run typecheck` clean.
- QA 2026-09-24 (orchestrator, first-hand): unit lane 2299 passed + ruff clean; integration lane 130 passed on a disposable Postgres 16 at alembic head; frontend tsc, eslint and vitest 593 all green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
