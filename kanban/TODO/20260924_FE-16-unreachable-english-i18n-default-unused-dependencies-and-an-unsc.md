---
id: FE-16
title: "Unreachable English i18n default, unused dependencies, and an unscoped global CSS surface"
severity: low
area: frontend
labels: [tech-debt, documentation]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# FE-16 — Unreachable English i18n default, unused dependencies, and an unscoped global CSS surface

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** tech-debt, documentation

**Trạng thái:** TODO

## Problem

`frontend/src/lib/i18nProvider.ts` is an English default that the runtime always overrides, so "which locale am I in" has two answers. Four declared dependencies have no importers, and the CSS surface is one 48 KB global sheet plus ~19 feature stylesheets that are not actually scoped by module because their selectors nest under a shared global container class.

## Evidence

- `frontend/src/lib/i18nProvider.ts` is imported as the default at `components/admin/admin.tsx:9`, but `App.tsx:3` and `components/atomic-crm/root/CRM.tsx:73` always supply the Vietnamese provider, making the English default unreachable in production.
- `frontend/package.json:48,51,55,61` — `@tanstack/query-async-storage-persister`, `@tanstack/react-query-persist-client`, `diacritic` and `qs` have no importers in `src`; `lib/vietnameseSearch.ts` implements its own normalisation and query strings use `URLSearchParams`.
- `frontend/src/index.css` is 49,208 bytes (48.1 KB) and `conversations/inbox/` holds 19 stylesheets (`chat.css` 32.6 KB, `features.css` 30.9 KB, `untitledui-conversations.css` 21.7 KB, `personas-studio.css` 19.7 KB, `tokens.css` 13.3 KB), plus `integrations/settings.css` 37.8 KB, `projects/projects.css` 30.2 KB and `performance/performance.css` 27.7 KB.
- Selectors are nested under a global container class rather than scoped per module — `conversations/inbox/chat.css` alone has 170 `inbox-bg-container` rules (`.inbox-bg-container .bubble` at `:996`) and `context-drawer.css` has 145, including `.inbox-bg-container .candidate-info-row[data-field="notes"]` at `:741`.
- Positive signs to preserve: the hoisted `--tt-*` token bridge in `kit/tailkit-system.css`, `contain: layout style paint` at `conversations/inbox/chat.css:967`, `:1007` and `:1021`, and the dedicated CSS regression tests.

## Impact

Four packages of audit and `npm ci` surface buy nothing, the locale question has two answers, and feature CSS remains reachable by any global rule.

## Suggested fix

Delete `frontend/src/lib/i18nProvider.ts` (or make the admin default Vietnamese), remove the four confirmed-unused dependencies after checking `scripts/` and `*.mjs` hooks, and scope the feature stylesheets under a per-module container class instead of the shared `.inbox-bg-container`.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
