---
id: FE-19
title: "Feature stylesheets are not scoped by module; selectors nest under one global container class"
severity: low
area: frontend
labels: [tech-debt]
effort: L
status: dev_completed
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

## Evidence log

- 88e3866d — bounded the debt rather than doing the forbidden big-bang. `.inbox-bg-container` is carried by six workspace roots (inbox, profile, project, persona, settings, knowledge); **691** selectors nest under it as a descendant and reach all six screens, while only **11** use the compound form `projects.css` already proves out. `chat.css` alone contributes 159, `context-drawer.css` 140.
- `src/components/atomic-crm/css-scoping.test.ts` counts descendant selectors across every stylesheet in `src/` and fails above 691. Proven to bite: at a cap of 690 it fails with "rose from 690 to 691" and lists the worst files, so the number can only fall. Per-file counts matched an independent Python pass exactly.
- Second assertion keeps the compound `.inbox-bg-container.<workspace>` pattern in use so a cleanup cannot delete the last good example. The suite runs in the browser project, so sheets load via `import.meta.glob`, not `node:fs`.
- `frontend/AGENTS.md` now documents the convention and names `MAX_UNSCOPED_RULES` as the thing to lower when a sheet gets scoped.
- STILL OPEN by design: the 691 rules are not folded. The card and the audit both forbid a batch rewrite — it needs visual QA per screen because TEST-10's CSS tests assert source text, not rendered layout. Each sheet gets scoped the next time it is opened; this commit only stops the count growing.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
