---
id: FE-17
title: "registry.json is not the generator's output and registry:check already fails at HEAD"
severity: medium
area: frontend
labels: [tech-debt, testing]
effort: M
status: in_progress
column: TODO
opened: 2026-09-24
---

# FE-17 — registry.json is not the generator's output and registry:check already fails at HEAD

**Severity:** medium · **Area:** frontend · **Effort:** M · **Labels:** tech-debt, testing

**Trạng thái:** TODO

## Problem

`frontend/registry.json` is a tracked generated artifact that no longer matches what `scripts/generate-registry.mjs` produces, and `npm run registry:check` fails at HEAD before any change. Nothing gates on it, so the drift has accumulated invisibly.

## Evidence

- `npm run registry:check` at HEAD fails with 16 errors: `missing manifest path: CHANGELOG.md` plus 15 `unpublished local dependency` errors (e.g. `PerformancePage.tsx -> PerformanceTrendChart.tsx`, `ZaloIntegrationPage.tsx -> CredentialSecretField.tsx`, `ChannelAdapterSelector.tsx -> src/assets/channel-adapters/facebook-messenger.svg`).
- Running `node scripts/generate-registry.mjs` produces a file that differs from the checked-in one by ~200 entries: it **drops every `registry:style` entry** (all 20 `conversations/inbox/*.css`, `dashboard.css`, `integrations/settings.css`, `kit/tailkit-system.css`, `users.css`, `layout/mobile-workspace.css`, `performance.css`, `projects.css`) and **adds test-only files the checker explicitly rejects** (`src/lib/vietnameseSearch.test.ts`, `src/lib/apiClient.test.ts`, `src/lib/apiClient.refresh.test.ts`) — so the generator is stale relative to the checked-in manifest, not the other way round.
- `scripts/check-registry-paths.mjs` is invoked only by `registry:check`/`registry:build`, neither of which runs in `.github/workflows/quality-gates.yml` — hence the silent drift.
- Consequence during this work: creating any new helper file imported by a registry-published file adds another `unpublished local dependency` error, so the check cannot be used as a gate until the manifest is rebuilt deliberately.

## Impact

`registry.json` is published application TS and CSS, so a stale manifest ships the wrong file set to consumers of the admin registry, and the one check that would catch it cannot pass — so it is ignored and drifts further. Every new shared helper silently widens the gap.

## Suggested fix

Decide what the registry is for and make it authoritative. Either (a) fix `scripts/generate-registry.mjs` to emit `registry:style` entries and to exclude `*.test.*` (matching `check-registry-paths.mjs`'s own rules), regenerate once, and add `npm run registry:check` to the `frontend-quality` CI job so it cannot drift again; or (b) stop publishing a manifest at all and delete `registry.json` plus its scripts. Either way, resolve the 15 `unpublished local dependency` errors by publishing the imported helpers or by narrowing what the published entries reference, and fix the `CHANGELOG.md` manifest path. Do not regenerate blindly — the generator is currently the less correct of the two files.

## Notes

Discovered while executing FE-06 (three kit entries were hand-removed so no manifest path points at a deleted file). Pre-existing at HEAD; not caused by FE-06.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
