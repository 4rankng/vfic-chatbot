/**
 * Tailkit-inspired primitives for the TingHire recruiter console.
 *
 * These are presentational components adapted from the Tailkit `application-ui`
 * catalog. They consume the `--tt-*` token bridge declared in
 * `kit/tailkit-system.css` on `.workspace-frame`, and compose over the existing
 * shadcn / daisyUI primitive layer — they do NOT replace `tt-*` classes.
 *
 * The `--tt-*` bridge is declared here on `.workspace-frame`, which is the only
 * block that sets those names for workspace content. `conversations/inbox/tokens.css`
 * declares a second `--tt-*` set on `:root` (plus inbox-only keys such as
 * `--tt-surface`, `--tt-surface-hover` and `--tt-sidebar-*`). Measured in the
 * built CSS on 2026-09-28: the kit's `.workspace-frame` block wins for every key
 * both define, because `:root` and `.workspace-frame` have the same specificity
 * and the inbox's block is inherited rather than matched by workspace elements.
 * The inbox's `:root` set therefore reaches only `<html>` — in practice, portaled
 * UI (Radix dialogs, menus, popovers) rendered outside `.workspace-frame`.
 * Consolidating the two sets would move those portals, so it stays deferred.
 *
 * Design rationale: `frontend/AGENTS.md` § "UI/UX Component Sourcing", plus
 * `plans/reports/260928-ui-surface-audit.md` for the per-surface mapping.
 */
export { PageHeading, default as PageHeadingDefault } from "./page-heading";
export { EmptyState, PageShell } from "./page-shell";
