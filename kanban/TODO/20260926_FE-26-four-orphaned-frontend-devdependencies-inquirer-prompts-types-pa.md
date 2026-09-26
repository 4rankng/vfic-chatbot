---
id: FE-26
title: "Four orphaned frontend devDependencies: @inquirer/prompts, @types/papaparse, @types/qs, @types/ms"
severity: low
area: frontend
labels: [frontend, dependencies, hygiene]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# FE-26 — Four orphaned frontend devDependencies: @inquirer/prompts, @types/papaparse, @types/qs, @types/ms

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, dependencies, hygiene

**Trạng thái:** TODO

## Problem

Four devDependencies have zero usage anywhere in the frontend: @inquirer/prompts is imported by no script, config, or test; @types/papaparse, @types/qs and @types/ms type packages that are not dependencies and are never imported. They look like leftovers from the wave-1 six-package orphan removal that dropped the packages but not their type/CLI companions.

## Evidence

- frontend/package.json:79 — "@inquirer/prompts": "^8.2.0" (devDependencies); no @inquirer import in src/, e2e/, scripts/, or configs
- frontend/package.json:85-86 — "@types/papaparse", "@types/qs"; no `from "papaparse"` / `from "qs"` import exists (papaparse appears only as a third-party entry in registry.json:24, a manifest, not an import or installed dep)
- frontend/package.json:83 — "@types/ms"; no `from "ms"` import exists anywhere
- frontend/scripts/generate-registry.mjs:3 — `import { globSync } from "glob"` confirms the remaining dev tooling (glob, globals, typescript-eslint, eslint-plugin-react-refresh, @vitest/browser-playwright) is genuinely used and was checked

## Impact

Install weight and lockfile churn for types of packages that are not even installed; mild signal noise for the next orphan sweep.

## Suggested fix

Remove the four entries from frontend/package.json devDependencies and run npm install to sync package-lock.json. Dependency manifests are approval-gated per AGENTS.md — get the owner sign-off with the removal diff.

## Notes

daisyui, tw-animate-css, @tailwindcss/typography and @fontsource/be-vietnam-pro were checked and ARE used via src/index.css — not orphans.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
