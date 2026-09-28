/**
 * Tailkit-inspired primitives for the TingHire recruiter console.
 *
 * These are presentational components adapted from the Tailkit `application-ui`
 * catalog. They consume the `--tt-*` token bridge declared in
 * `kit/tailkit-system.css` on `.workspace-frame`, and compose over the existing
 * shadcn / daisyUI primitive layer — they do NOT replace `tt-*` classes.
 *
 * The `--tt-*` bridge is scoped to `.workspace-frame`; `conversations/inbox/tokens.css`
 * re-declares an overlapping `--tt-*` set on `:root` and on `.workspace-frame`
 * for the inbox, so on inbox routes the inbox's values win for the keys it
 * declares. Consolidating those two sets is deferred — it moves pixels on the
 * most screenshot-covered surface in the app.
 *
 * Design rationale: `frontend/AGENTS.md` § "UI/UX Component Sourcing", plus
 * `plans/reports/260928-ui-surface-audit.md` for the per-surface mapping.
 */
export { PageHeading, default as PageHeadingDefault } from "./page-heading";
export { EmptyState, PageShell } from "./page-shell";
