/**
 * Tailkit-inspired primitives for the TingHire recruiter console.
 *
 * These are presentational components adapted from the Tailkit `application-ui`
 * catalog. They consume the `--tt-*` token bridge declared in
 * `conversations/inbox/tokens.css` and compose over the existing shadcn /
 * daisyUI primitive layer — they do NOT replace `tt-*` classes.
 *
 * See `plans/<timestamp>-tailkit-overhaul/` for the full design rationale.
 */
export { PageHeading, default as PageHeadingDefault } from "./page-heading";
export { EmptyState, PageShell } from "./page-shell";
