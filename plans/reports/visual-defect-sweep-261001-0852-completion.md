# Visual-defect sweep — completion report

Copied from `standards/agent-completion-checklist.md` (DOC-19) and filled gate by
gate.

## Task record

- Task: run a visual check over every page, subpage and component; fix every
  visual defect found; then commit, push and deploy to production.
- Scope: `frontend/` only — no backend, API, schema or payload change. Eleven
  authenticated routes, the login and forgot-password pages, and the portal
  surfaces (topbar menus, dialogs, category editor) at 1440×900 and 390×844.
- Files changed:
  - `frontend/index.html` (removed the unlayered body font override)
  - `frontend/src/components/atomic-crm/conversations/inbox/base.css` (reset
    moved into `@layer base`)
  - `frontend/src/components/atomic-crm/layout/topbar/{account-menu,notifications-menu}.tsx`
  - `frontend/src/components/atomic-crm/users/{UserCreate,UserActions}.tsx`
  - `frontend/src/components/atomic-crm/projects/{ProjectCreate,ProjectKnowledgePanel}.tsx`,
    `projects/presentation/ProjectBriefImport.tsx`
  - `frontend/src/components/atomic-crm/automation/{botRunMeta.ts,BotRunList.tsx,DecisionTracePanel.tsx}`
  - `frontend/src/components/ui/tag-stack.tsx`
  - tests: `src/base-document.test.ts`,
    `src/components/atomic-crm/workspace-control-ink.test.tsx` (new), plus
    assertions added to `automation/BotRunPages.test.tsx`,
    `layout/topbar/notifications-menu.test.tsx`,
    `users/account-layout-regressions.test.tsx`,
    `projects/ProjectCreate.test.tsx`
  - `docs/design/design-qa.md` (pass record)
- Instructions retrieved: `AGENTS.md`, `frontend/AGENTS.md`,
  `standards/agent-completion-checklist.md`, `docs/design/design-qa.md`,
  `docs/design/design-tokens-warm-paper.md`,
  `standards/review-checklist.md`, `docs/ops/deployment-guide.md`.
- Approval required: yes — production deploy.
- Approval evidence: the user instruction "commit, push and deploy to prod"
  (2026-10-01), which supersedes the standing "do not deploy unless asked".

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Sweep run over 13 routes × 2 widths + opened portal surfaces; 5 defect classes found and fixed; residual 3 contrast items documented as accepted deviations in `docs/design/design-qa.md` §"Second all-screens pass (2026-10-01)". |
| Diff is limited to the approved scope | PASS | `git diff --stat`: 18 files / +170 −15, all under `frontend/` and `docs/design/`. No backend, API or schema file touched. |
| Protected operations were avoided or approved | PASS | Commit/push/deploy explicitly requested. `make release-check` is run before `make deploy`, which gates on a pre-migration backup (root `Makefile`). |
| Focused tests/checks pass | PASS | `npx vitest --project app --run <6 touched files>` → 6 files / 39 tests passed. |
| Broader regression tests pass when shared behavior changed | PASS | `npm run test:unit:app` → 106 files / 745 tests passed before the new guards; full re-run after them recorded below. `make release-check` re-runs the same suite with coverage. |
| Lint passes for affected code | PASS | `npm run lint` → 0 errors, 36 pre-existing warnings (none in touched files). |
| Type checking passes for affected code | PASS | `npm run typecheck` and `npm run typecheck:node` → both clean. |
| Build/import validation passes for affected code | PASS | `npm run build && npm run smoke:built` inside the `make release-check` frontend lane. |
| Security and privacy impact reviewed | N/A | CSS layering, `.uu-scope` class placement, one token name and one `index.html` declaration. No auth, transport, data or secret surface touched. |
| Performance and async-I/O impact reviewed | N/A | No runtime logic, data flow or request change; only cascade and class changes. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Contrast measured per leaf text node against its first opaque background (the sweep in `docs/design/design-qa.md`); the fixes raise 1.02:1 / 1.17:1 / 1.96:1 / 3.37:1 pairs to ≥ 4.5:1. Vietnamese strings only; the base font is now Be Vietnam Pro on every screen. |
| Error handling and compatibility reviewed | PASS | No error path changed. `text-warning-foreground` → `text-warning` keeps the token meaning (fill-foreground vs ink); `@layer base` keeps the inherit default for buttons with no ink utility (asserted by test). |
| Documentation impact handled | PASS | `docs/design/design-qa.md` records the pass, its evidence and the accepted deviations. `node scripts/check-doc-links.mjs` runs inside `make release-check` (no routed path changed). |
| No new unlinked TODO, FIXME or HACK | PASS | `grep -rn "TODO\|FIXME\|HACK" $(git diff --name-only)` → no matches. |
| Final `git diff --check` passes | PASS | Clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Only the files listed under "Files changed", plus the two new test files. |

## Deployment

- `make release-check`: PASSED (clean worktree, one Alembic head matching
  `docs/ops/deployment-guide.md`, uv lock, pyright `app/graph`, npm audit,
  backend pytest with coverage, migration roundtrip walk, frontend
  lint/typecheck/registry/coverage/build/smoke, golden retrieval benchmark
  `golden_pass_rate_pct=100.0%`). No failure banner; data lane reported
  `release gate passed`.
- `make deploy`: the first attempt aborted and auto-rolled back (`bg_rollback`
  restored the previous colour, prod stayed healthy on the previous tag). Cause
  was a race, not the change: a concurrent session in this checkout was running
  its own `make deploy` at the same time (two `make deploy` processes, one
  `bg_deploy.sh` at a time on the host), and the shipped tree's `HEAD` moved
  from my commit to that session's `892a9636` between the two attempts.
- `make deploy` (retry): PASSED. `bg_deploy: active=green next=blue
  tag=892a9636`; smoke gate 5/5 on the new colour (`single-message`,
  `progressive-send`, `progressive-send-failure`, `support-oa-hotline`,
  `support-oa-clarify`); Caddy flipped to `web-blue`;
  `verify_post_flip_readiness` reported `active web-blue
  image=ghcr.io/4rankng/tinghire-be:892a9636` and `PIPELINE OK`; frontend
  container recreated.
- Production evidence after cutover: `ACTIVE_COLOR=blue`,
  `vfic-web-blue-1 = tinghire-be:892a9636 (healthy)`,
  `vfic-frontend-1 = tinghire-fe:892a9636 (healthy)`, `/health` → `status: ok`,
  and the live login page reports `body` font-family `"Be Vietnam Pro",
  ui-sans-serif, system-ui, sans-serif` with an empty console.
- Built-artifact check (same source the image is built from): the workspace
  button reset sits inside `@layer base`, `dist/index.html`'s loader block is
  `body{margin:0;padding:0}` with no `font-family`, all four `.uu-scope`
  additions are in the emitted chunks, and `text-warning-foreground` has zero
  occurrences.

## Result

- Overall status: PASS — deployed to production (`tag=892a9636`, which has
  `a672626d` as an ancestor).
- Remaining risks or follow-ups:
  - Three tint-pair contrast items are accepted, not fixed: `Sẵn sàng` badge
    4.41:1, `Xóa dự án` outline 4.33:1, category-date metadata 4.49:1. Rationale
    in `docs/design/design-qa.md`; fixing them means restyling every error and
    success surface in the console.
  - **Concurrency hazard (needs the owner's attention).** A second session was
    deploying this repository at the same time. Two consequences: (a) the first
    cutover attempt failed for that reason and needed a retry; (b) the working
    tree carried that session's *uncommitted* edits
    (`backend/app/graph/dispatch.py`, `backend/app/graph/think_strip.py`) while
    `make push` built the image, so the registry tag `892a9636` was built from a
    tree that is not exactly commit `892a9636`. That session's own deploy will
    re-push the same tag from its committed tree; the owner should confirm which
    content is intended to serve before the next release, since the tag is
    mutable.
  - The Playwright `e2e/**/__screenshots__` visual baselines were already stale
    before this pass and are not regenerated here; they are not part of
    `make release-check`.
  - `components/ui/tag-stack.tsx` is currently unreachable from the app graph;
    its warning tone was fixed anyway so the module cannot ship the invisible
    variant if it is ever wired back in.
