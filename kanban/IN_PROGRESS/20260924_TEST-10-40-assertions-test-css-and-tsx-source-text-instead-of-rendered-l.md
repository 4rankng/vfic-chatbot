---
id: TEST-10
title: "~40 assertions test CSS and TSX source text instead of rendered layout"
severity: medium
area: testing
labels: [testing, tech-debt]
effort: L
status: in_progress
column: TODO
opened: 2026-09-24
---

# TEST-10 — ~40 assertions test CSS and TSX source text instead of rendered layout

**Severity:** medium · **Area:** testing · **Effort:** L · **Labels:** testing, tech-debt

**Trạng thái:** TODO

## Problem

Nine frontend test files import stylesheets or component source via `?raw` and assert regexes against the text, which passes when a selector is misspelled, shadowed by a later rule, or applied to an element that is never rendered — exactly the regressions the test names claim to prevent — and fails on any reformat. The `app` vitest project already runs in real Chromium, so computed styles are available and cheap.

## Evidence

- `frontend/src/components/atomic-crm/integrations/settings.css.test.ts:3-7` (5 raw imports) plus `:10-100` (12 assertions such as `--settings-control-height:\s*38px` and `min-height:\s*44px`).
- Eight further files use the same pattern: `conversations/inbox/responsive-visual-regressions.test.ts:3-4`, `kit/tailkit-system.css.test.ts:3`, `projects/projects.css.test.ts:3`, `performance/performance.css.test.ts:3-6`, `personas/persona-layout-regressions.test.ts:3-9`, `users/account-layout-regressions.test.ts:3-8`, `knowledge/knowledge-workspace-layout.test.ts:3-6` and `conversations/inbox/tailkit-redesign.test.ts:3`.
- `frontend/src/components/atomic-crm/conversations/ConversationList.test.ts:3` — imports component source via `?raw` rather than rendering the component.
- `frontend/vitest.config.ts:47-58` — the `app` project runs in real Chromium, so computed styles and layout rects are measurable in the existing lane.

## Impact

`expect(stylesheet).toMatch(/min-height:\s*44px/)` passes when the rule never applies to a rendered element, so the touch-target, viewport-overflow and hidden-metadata regressions the tests are named for are not actually guarded.

## Suggested fix

Render the component and assert `getComputedStyle(el).minHeight === "44px"`, or assert `el.getBoundingClientRect()` fits the mobile viewport at the mobile breakpoint. Convert the highest-value cases (touch targets, viewport overflow, hidden metadata) and delete the rest rather than re-pinning them.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
