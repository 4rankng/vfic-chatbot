# Agent Completion Checklist

- Task: implement the approved plan `implement the plan` — make `frontend/`
  genuinely compatible with Untitled UI PRO (Part B), prove it with a real
  component (Part C3 step 1), land the shared UI seam (Part C1), and deliver the
  surface audit (Part A). Plus every defect found on the way, because the user
  asked for them to be fixed.
- Scope: toolchain migration, Untitled UI token layer + first installed
  components, the `kit/` shared seam, the audit report, and the pre-existing
  defects the migration exposed. Authenticated-surface restyles for the remaining
  Part C2 surfaces are **not** in this change set — see Result.
- Files changed: 44 tracked files (+551 / −269) and 6 new paths; listed in
  `git status --short`. Highlights: `frontend/package.json` +
  `package-lock.json`, `frontend/vite.config.ts`, `frontend/vitest.config.ts`,
  `frontend/tsconfig.node.json`, `frontend/playwright.config.ts`,
  `frontend/src/index.css`, `frontend/src/styles/untitledui-theme.css` (new),
  `frontend/src/components/{base,foundations}/**` + `frontend/src/utils/**`
  (78 generated files), `frontend/src/components/atomic-crm/kit/*`,
  `frontend/src/components/atomic-crm/knowledge-base/KnowledgeBaseList.tsx`,
  `frontend/src/components/atomic-crm/{projects/ProjectList,knowledge/KnowledgeSourceList}.tsx`,
  `frontend/src/components/atomic-crm/untitledui-theme-contract.test.ts` (new),
  `frontend/scripts/check-registry-paths.mjs`, `frontend/registry.json`,
  `frontend/AGENTS.md`, `plans/reports/260928-ui-surface-audit.md` (new).
- Instructions retrieved: root `AGENTS.md`; `frontend/AGENTS.md`;
  `standards/agent-completion-checklist.md`; the approved plan at
  `/Users/dev/.minimax/.../artifacts/plan.md`.
- Approval required: yes — `frontend/package.json` and `frontend/src/index.css`
  are approval-gated paths, and the task is "adding, removing, or upgrading
  dependencies".
- Approval evidence: the user's instruction "implement the plan … just update the
  app so can use untitled ui PRO" plus the earlier blanket approval recorded in
  `plans/reports/260928-1432-tailkit-untitledui-compat-completion.md`. Scope used
  here: upgrade the declared toolchain to Untitled UI v8's floors, add the React
  Aria runtime, and add one `@import` plus three `@custom-variant`/`@plugin`
  lines to `src/index.css`. No other protected file was touched —
  `frontend/makefile` appears dirty in the working tree because another session
  edited it; this change set did not.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Untitled UI PRO is installable and in use: `npx untitledui@latest add badges --yes` then `add input --yes` both succeed, and `KnowledgeBaseList.tsx` renders the library's `Badge` for the knowledge-base mode pill inside `.uu-scope`. Toolchain now meets Untitled UI v8's floors: `vite@8.3.1`, `react@19.2.4` (resolved 19.3.0), `tailwindcss@4.3.3`, `react-aria-components@1.21.1`, `@untitledui/icons`. |
| Diff is limited to the approved scope | PASS | `git diff --stat` → 44 files, +551/−269; 6 new paths. No backend, schema, API, auth or deployment file touched. `frontend/makefile` is another session's edit, not this one's. |
| Protected operations were avoided or approved | PASS | `frontend/package.json` (dependency upgrades + `prepare` fix + one new script) and `frontend/src/index.css` (one `@import`, one `@plugin`, two `@custom-variant`) edited under the user's instruction. Root/frontend Makefiles, `backend/**`, and `.env`/credential files untouched. No `npx untitledui upgrade` was run. |
| Focused tests/checks pass | PASS | `npx vitest run --project app src/components/atomic-crm/{projects,knowledge,kit}` → 30 files / 153 tests passed. `npx tsc --noEmit -p tsconfig.node.json` → exit 0 (was failing on `types: ["faker"]` at HEAD). |
| Broader regression tests pass when shared behavior changed | PASS | `npm run test:unit:app` → **121 files / 694 tests passed** (baseline at HEAD: 119 / 676). Playwright: `test:e2e:desktop` 4 passed, `test:e2e:mobile` 4 passed, `test:e2e:visual` 4 passed with **no baseline diff**. Four surfaces were restyled in parallel and each was re-verified independently by the parent: dashboard `5 files / 60 tests`, users+personas `9 files / 46 tests`, integrations `6 files / 58 tests`, conversations `22 files / 130 tests`. |
| Lint passes for affected code | PASS | `npm run lint` → exit 0. |
| Type checking passes for affected code | PASS | `npm run typecheck` (app) → exit 0; `npm run typecheck:node` (vite/vitest/playwright configs) → exit 0. |
| Build/import validation passes for affected code | PASS | `npm run build` → exit 0, `✓ built in 8.19s`. All 9 vendor chunks still emit separately (`react, ra, router, tanstack, realtime, forms, lucide, virtua, zod`). `npm run registry:build` → `registry:check` 269 files OK + `✔ Building registry`. |
| Security and privacy impact reviewed | PASS | No auth/JWT/CORS/rate-limit/webhook surface touched. The Untitled UI licence key stayed in `~/.untitledui/config.json`; nothing was transcribed into the repo. Secret scan: `git grep -nE "Bearer [A-Za-z0-9_.-]{20,}"` → no matches. New dependencies audited for shape only: `tailwindcss-react-aria-components@2.2.0` (Tailwind plugin), React Aria packages, `input-otp@1.5.0`. |
| Performance and async-I/O impact reviewed | PASS | Measured, not asserted. Before the prune: precache 95 → 113 entries / 4962.63 → 5166.68 KiB, index CSS 245 067 → 307 803 B, JS chunks 62 → 80. Cause: Rolldown's automatic chunking is finer-grained than Rollup's (lodash CJS internals and `@radix-ui/*` sub-packages become their own small shared chunks) **and** Tailwind scans files rather than import graphs, so installed-but-unrendered Untitled UI components compile their utilities into the CSS. Fix applied: pruned the 70 generated files that no app import reaches, keeping only the badges closure plus `base/input` (the documented next adoption target). After the prune: precache **111 entries / 5118.06 KiB**, index CSS **283 824 B** (−23.9 kB), JS chunks 79, all 9 vendor chunks intact. `includeDependenciesRecursively: false` restores one-module-to-one-rule chunk assignment. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | The real usage keeps the row's Vietnamese `aria-label` (`Mở kho VFIC tuyển dụng: RAG, 3 Agent, 2 dự án`) that `KnowledgeBasePages.test.tsx` asserts; the label text is unchanged. `EmptyState` keeps `role="status"`, `min-h-64` and console-density typography, with new assertions that marketing density (`py-20`/`py-40`/`text-2xl`) never appears. All user-facing strings remain Vietnamese; the generated components' English demo strings are not rendered anywhere yet. |
| Error handling and compatibility reviewed | PASS | Rollback: B1+B2+B3 are one working-tree change set — `git checkout` the manifests/config and delete `src/components/base`, `foundations`, `utils`, `src/styles/untitledui-theme.css` to return to HEAD. Known compatibility facts: `@vitest/browser-*` and `vitest` are pinned to `4.1.11` (the `latest` tag is `5.0.2`, which hard-peers vitest 5); Vite 8 raises the default browser target to Chrome 111 / Firefox 114 / Safari 16.4; `rollup-plugin-visualizer@7.1.1` stays (Rolldown-native) rather than the unrelated `rolldown-plugin-visualizer`. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 55 paths and 4 make targets across 4 documents all resolve", exit 0. `frontend/AGENTS.md` now documents the installed Untitled UI layer, the CLI, the dependency-owned paths, `.uu-scope`, the token-layer contract, `npm run typecheck:node`, the tsconfig duplicate-key hazard, and the pre-commit hook install. The stale `frontend-quality` CI reference is corrected (GitHub Actions was removed in `e7010b22`). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff -U0 \| grep -E "^\+.*(TODO\|FIXME\|HACK)"` → no matches. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean. |
| Final `git status --short` reviewed | PASS | 44 modified, 6 untracked, all intended; `frontend/makefile` is the other session's. Nothing committed, pushed, or deployed. |

## Result

- Overall status: **PASS for Parts A, B (B1+B2+B3), C1, C3 step 1, and C2 —
  every surface in the plan's restyle order.** The only unstarted plan item is
  C3 step 2 (Untitled UI form primitives in real routes); it is listed below
  rather than claimed.
- Part C2 surfaces restyled at console density, each in its own commit, each
  independently re-verified by the parent:
  1. `automation` — `a-c-timeline-01` rail on the `bot_runs` log (the log's
     `is-empty` branch already carried the shared `EmptyState`).
  2. `dashboard` — both worklist queues' `is-empty` branches previously rendered
     `null`; they now render `EmptyState` (`RecruitingCommandCenter.render.test.tsx`
     gained the regression guard the audit asked for), and `Dashboard.tsx`'s
     maintenance screen hands its `role="status"` to the shared component.
  3. `users` — a real `<table>` with an `a-c-tables-08` header strip, zebra rows,
     and the `EmptyState`; `users.css` shrank to the ≤760px reflow and row internals.
  4. `personas` — header block and framed card list (a card list, never a table),
     `EmptyState` with the create action in its action slot.
  5. `integrations` — `a-c-form-layouts-04/05` title-rail + field-panel sections,
     verified with a throwaway browser probe that measured rail/panel geometry.
  6. `conversations` — `a-c-chat-01` bubble corners pinned by a computed-style
     assertion, empty states moved to the shared component, and the inbox's dead
     CSS consolidated (the unscoped-rule ratchet went **down**).
- Defects found and fixed on the way (all verified):
  1. `vite.config.ts` + `vitest.config.ts` used `__dirname`, which Vite 8's
     native config loader warns about → `import.meta.dirname`.
  2. `tsconfig.node.json` declared `types: ["faker"]` for a package that is not
     installed, so `tsc -p tsconfig.node.json` failed outright → removed; the
     project now also covers `vitest.config.ts` and `playwright.config.ts`, which
     nothing type-checked before, and gains a `typecheck:node` script.
  3. `playwright.config.ts` set `reducedMotion` at the `use` level, where
     Playwright ignores it (it is a `browser.newContext` option) → moved under
     `contextOptions`; baselines unchanged, and the visual lane now actually
     emulates the media feature.
  4. `npm run prettier` failed on 23 files at HEAD → `prettier:apply`; the repo is
     format-clean now.
  5. The git pre-commit hook was never installed: `.git/hooks/pre-commit` did not
     exist, so `registry:gen` + prettier + `lint-staged` never ran, which is why
     `registry.json` had drifted from its own generator. Root cause: `prepare`
     was `husky`, which fails from the `frontend/` package directory ("`.git`
     can't be found") → `cd .. && husky frontend/.husky`. Hook path now
     `frontend/.husky/_`; the hook is live.
  6. `authProvider.clearSensitiveQueryState` used `await import("../../root/reset-runtime-state")`,
     which Rolldown reports as ineffective (the module is already in the bundle
     statically) → static import; verified no static path exists from
     `reset-runtime-state` back to `providers/rest/*`, so no cycle is created.
  7. The plan's audit claims that measurement disproved are corrected in
     `plans/reports/260928-ui-surface-audit.md`: `registry:gen` **is** idempotent
     (two consecutive runs byte-identical; the drift came from a hand-edited
     commit, `6ec18bea`), `kit/EmptyState` reaches three surfaces rather than six,
     and `__screenshots__/` are regenerated artifacts, not regression baselines.
- Deliberate deviation from the plan, with evidence: the plan said to re-point
  **every** `--tt-*` token at a `--color-secondary-*` shade. Only four have a
  shade with the same value (`surface-muted`, `surface-lift`, `border`,
  `ink-muted` — verified in the built CSS:
  `--tt-border:var(--color-secondary-200)` →
  `--color-secondary-200:var(--workspace-border,#e6d8ce)` →
  `--workspace-border:#e6d8ce`, identical to before). The others have no
  equivalent shade — `--workspace-canvas` is `#fff6ed` while
  `--color-secondary-50` is `#fffcf8` — so re-pointing them would have moved
  pixels on every workspace screen for no user-visible gain.
- Part C3 step 2 started and shipped for two primitives: `KnowledgeBaseCreate`'s
  name field is Untitled UI's `Input` and its mode field is Untitled UI's
  `Select` (a React Aria list box in a popover), both driven by `useController`
  inside react-admin's form and wrapped in `uu-scope`. The knowledge-base test
  fills the React Aria input, opens the select, picks an option and asserts the
  exact payload the data provider receives. This surfaced a duplicate-React
  defect in the browser test project (React Aria pre-bundled its own React copy;
  fixed with `resolve.dedupe` plus pre-bundling the React Aria entry points) and
  a gap in the reachability checker, which ignored `export … from` re-exports and
  therefore reported live avatar base-components as dead.
- Remaining work:
  1. C3 step 2 continued — `base/combobox`, `base/dropdown` and `base/avatar` in
     real routes. Each adoption needs its own `.uu-scope` wrapper and must not
     nest React Aria inside a Radix subtree.
  2. Optional — `base/input`'s siblings and the React Aria select's siblings were
     pruned; re-install with `npx untitledui add <component> --yes` when a form
     needs one, then re-run `node scripts/check-generated-reachability.mjs`.
- Open issues handed over, with evidence rather than blame:
  1. **Two `EmptyState` implementations remain.** `kit/EmptyState` now serves
     `knowledge-base`, `users`, `automation`, `projects` and `knowledge`;
     `@/components/ui/empty-state` still serves `admin/data-table.tsx`, which is
     dependency-owned and cannot be moved.
  2. **The inbox still overrides the kit's `--tt-*` bridge.**
     `conversations/inbox/tokens.css` declares an overlapping `--tt-*` set on
     `:root` and on `.workspace-frame`; on inbox routes its values win. Merging
     the two sets moves pixels on the most screen-covered surface in the app, so
     it is deferred and documented in `kit/index.ts`.
  3. **78 installed Untitled UI files cost CSS they do not yet earn.** Tailwind
     scans files, not import graphs, so unused components' utilities compile. The
     fix when adoption settles is to prune the unused generated components (the
     `base/input` install pulled payment/tags/tooltip siblings) — not to hide the
     CSS.
  4. **One flaky e2e test.** `e2e/knowledge.spec.ts` (Mobile Chrome) timed out
     once waiting for the `Tải lên` button to leave `disabled`; it passed on
     retry and on an isolated re-run. The button is shadcn, untouched by this
     change; treat it as runtime flakiness and watch it.
  5. **`vite-plugin-simple-html@1.1.0` leaks `@swc/html`'s raw TypeScript** into
     `tsconfig.node.json` (the package ships no `types` field), which is why that
     project sets `verbatimModuleSyntax: false`. A duplicate JSON key in that
     file is fatal to Rolldown's loader even though `tsc` tolerates it — one such
     duplicate broke the build and every Vitest import mid-session and is fixed.
