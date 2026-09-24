---
id: FE-19
title: "Feature stylesheets are not scoped by module; selectors nest under one global container class"
severity: low
area: frontend
labels: [tech-debt]
effort: L
status: todo
column: TODO
opened: 2026-09-24
---

# FE-19 — Feature stylesheets are not scoped by module; selectors nest under one global container class

**Severity:** low · **Area:** frontend · **Effort:** L · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

Feature CSS is not scoped by module: selectors nest under a shared global container class, so any global rule can reach any feature's elements. The sheet surface is one 48 KB global `index.css` plus ~19 feature stylesheets.

## Evidence

- `frontend/src/index.css` is 49,208 bytes, and `conversations/inbox/` holds 19 stylesheets (`chat.css` 32.6 KB, `features.css` 30.9 KB, `untitledui-conversations.css` 21.7 KB, `personas-studio.css` 19.7 KB, `tokens.css` 13.3 KB), plus `integrations/settings.css` 37.8 KB, `projects/projects.css` 30.2 KB and `performance/performance.css` 27.7 KB.
- `conversations/inbox/chat.css` alone has ~170 `inbox-bg-container` rules and `context-drawer.css` ~145, including `.inbox-bg-container .candidate-info-row[data-field="notes"]`.
- Positive signs to preserve, not replace: the hoisted `--tt-*` token bridge in `kit/tailkit-system.css`, `contain: layout style paint` in `conversations/inbox/chat.css`, and the dedicated CSS regression tests.

## Impact

A global rule can silently restyle an unrelated feature, and there is no module boundary to reason about — but this is a maintainability cost, not a defect users can see.

## Suggested fix

Fold each feature sheet into Tailwind utilities or CSS modules **as those files are touched** — do not attempt a big-bang migration. The audit's own recommendation was to defer this and do it incrementally, which is why it is carded separately from FE-16 rather than bundled into it. Scope each feature under its own container class when you next open the file; verify visually, since the existing CSS tests assert source text rather than rendered layout (see TEST-10).

## Notes

Split out of FE-16, whose other two parts (the unreachable English i18n default and the unused dependencies) are done. Deferred deliberately: it needs browser QA per screen and the audit advised against a big-bang rewrite.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
