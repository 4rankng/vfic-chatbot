# Agent Completion Checklist

- Task: Make `frontend/` a host for Untitled UI and Tailkit MCP output (approved
  plan, Layers 1–2), and record the durable instruction that makes agents
  actually reach for those MCPs.
- Scope: Phase 1 (Tailkit `secondary-50…950` token scale + contract test) and
  Phase 2 (`@untitledui/icons` + `components.json` version 8 + sourcing docs).
  Phase 3 (Tailwind 4.3 / React 19.2.4 / Vite 8 / React Aria runtime) was
  deliberately NOT started — see Result.
- Files changed: `AGENTS.md`, `frontend/AGENTS.md`, `frontend/components.json`,
  `frontend/package.json`, `frontend/package-lock.json`,
  `frontend/src/index.css`, `frontend/src/styles/tailkit-tokens.css` (new),
  `frontend/src/components/atomic-crm/tailkit-contract.test.ts` (new),
  `frontend/src/components/atomic-crm/ui-design-dependencies.test.tsx` (new).
- Instructions retrieved: root `AGENTS.md`; `frontend/AGENTS.md`;
  `standards/agent-completion-checklist.md`. Docs consulted read-only for
  dependency facts (Tailwind 4.2/4.3 release notes, Vite 8 migration guide).
- Approval required: yes — `frontend/package.json` is an approval-gated path.
- Approval evidence: user granted "blanket approval" for manifest and toolchain
  changes in the scoping questionnaire, and later "please implement" via
  `/ak:agentkit`. Scope used here: one additive icon dependency. No upgrades, no
  removals, no protected file outside the one gate.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Plan Layers 1–2 delivered. Tailkit markup now resolves: `src/styles/tailkit-tokens.css` declares `--color-secondary-50…950` as `@theme`, imported once at `src/index.css:4`. Untitled UI icons installed and MCP round-trip proven (`search_icons(category:"users")` → `User01` → real export). |
| Diff is limited to the approved scope | PASS | `git diff --stat` = 6 files, +102 lines; plus 3 new files. No behavior, data, or backend change. The unrelated `registry.json` reorder that `registry:gen` produced was reverted (`git checkout -- frontend/registry.json`). |
| Protected operations were avoided or approved | PASS | `frontend/package.json` and `frontend/package-lock.json` touched under the user's blanket approval, additive only. `frontend/src/index.css` and `frontend/src/components/admin/`, `frontend/src/components/ui/`, Makefiles, and all secret files untouched. |
| Focused tests/checks pass | PASS | `npx vitest run --project app` on the two new files: 2 files, 7 tests passed. |
| Broader regression tests pass when shared behavior changed | PASS | `npm run test:unit:app` → 119 files, 676 tests passed, exit 0 (was 118/674 before this change; +1 file / +2 tests from `ui-design-dependencies.test.tsx`). |
| Lint passes for affected code | PASS | `npx eslint` on both new test files → exit 0. `npx prettier --check` on all 6 changed/added files → "All matched files use Prettier code style!". |
| Type checking passes for affected code | PASS | `npm run typecheck` (tsc --noEmit, tsconfig.app.json) → exit 0, run after the Phase 2 edits. |
| Build/import validation passes for affected code | PASS | `npm run build` → exit 0, "✓ built in 50.72s", PWA precache 95 entries / 4962.63 KiB — byte-identical to the pre-Phase-2 build, confirming the icon package tree-shakes to zero shipped bytes while nothing imports it. `npm run registry:build` → `registry:check` 269 files OK, then "✔ Building registry" — proves shadcn accepts `components.json` `version: "8"`. |
| Security and privacy impact reviewed | PASS | No auth, JWT, CORS, rate-limit, webhook, or network-call surface touched. Dependency audited before install: `@untitledui/icons@0.0.23`, MIT, only peer dep `react >= 16`, zero runtime deps, `sideEffects: false`. No secret, credential, or PII written to any file; no bearer token transcribed into the repo. `npm audit` reports 4 moderate advisories, all pre-existing and unrelated to this addition. |
| Performance and async-I/O impact reviewed | PASS | CSS-only token layer plus an unused ESM icon package. No new runtime work, no async, no I/O. Verified empirically: precache total unchanged at 4962.63 KiB across both builds. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | No user-facing screen was changed — this phase adds infrastructure only, so there is no visual regression surface. The token file is light-only, matching the console's light-only contract, so the `dark:` variants in Tailkit markup stay inert rather than half-styled. The smoke test asserts an icon renders as a labelled SVG with a viewBox. |
| Error handling and compatibility reviewed | PASS | Tailwind emits `@theme` variables on use, not eagerly; documented in the token file header so a fresh build without `--color-secondary-*` is not misread as a broken import. `@theme static` was considered and rejected after reading the 4.1.18 source — it is not a supported `@theme` param (supported: `source()`, `theme()`, `prefix()`, `important`, `reference`, `inline`). `frontend/AGENTS.md` records that Untitled UI React markup must not be pasted until Phase 3. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 55 paths and 4 make targets across 4 documents all resolve", exit 0 (was 54; the new `frontend/AGENTS.md` routing line is the added path). `frontend/AGENTS.md` gained a "UI/UX Component Sourcing" section (retrieval recipes, drop-in obligations, token contract); root `AGENTS.md` gained a task-routing line. Both are durable maintainer decisions, which AGENTS.md step 6 permits. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff -U0 \| grep -E "^\+.*(TODO\|FIXME\|HACK)"` → no matches. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean, no whitespace errors. |
| Final `git status --short` reviewed | PASS | 6 modified, 3 untracked, all intended and listed under Files changed. Nothing committed, pushed, or deployed. |

## Result

- Overall status: PASS for Layers 1–2. Layer 3 (Untitled UI React components)
  is intentionally not started and is the open item below.
- Remaining risks or follow-ups:
  1. **Layer 3 is blocked, not done.** Every Untitled UI base component and page
     template declares `react-aria-components@^1.21.1` + `@untitledui/icons`,
     and v8 requires Vite `^8.0.0`; `@vitejs/plugin-react@4.7.0` peer-excludes
     Vite 8. Vite 7→8 is a Rolldown/Oxc + Lightning CSS migration touching
     `vite.config.ts` (`esbuild.keepNames` → `oxc`, `rollupOptions` →
     `rolldownOptions`, `manualChunks` → `codeSplitting`, `preserveSymlinks`)
     with two unverified Rollup-era plugins. It needs its own reviewed change.
  2. **No production screen has used a Tailkit component yet**, so the scale's
     runtime effect is proven by the contract test and the build, not by visual
     QA. AGENTS.md TEST-10 requires per-screen visual QA before trusting a
     stylesheet; that check is still owed for the first real drop-in.
  3. **The MCP servers are not registered for this repository.** `untitledui` and
     `tailkit` exist only in the MiniMax Code plugin
     (`~/.minimax/plugins/design-mcp/mcp.json`); this repo's `.mcp.json` holds
     only `repowise`. A Claude Code session here has neither tool, so the new
     sourcing instruction is inert there. Registration is deliberately deferred
     because it means copying bearer credentials — that is a user decision, not
     an agent one.
  4. **`registry:gen` is not idempotent** (pre-existing, unrelated). It stably
     reorders `leads/domain/candidateProfile.ts` against
     `leads/domain/leadLookupKey.ts`, while AGENTS.md states the command must
     stay idempotent and the diff should only add. Worth a separate fix.
  5. **Overhaul scope is still undecided.** No existing screen was restyled.
     "Dashboard" is a triage worklist (`RecruitingCommandCenter`, 734 lines) that
     does not match Tailkit's `a-c-statistics-*`, and the login route is already
     a bespoke branded layout. A target surface is needed before restyling
     working, screenshot-baselined screens.
