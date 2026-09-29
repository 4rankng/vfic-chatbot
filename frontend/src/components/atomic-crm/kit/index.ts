/**
 * Shared console primitives for the TingHire recruiter console.
 *
 * These are the app-level building blocks every resource screen composes:
 * `PageShell` (page column), `PageHeading` (title/subtitle/actions) and
 * `EmptyState`. They render on Untitled UI anatomy and the console's own
 * `--fs-*` role tokens, so a change here moves every route.
 *
 * Design rationale: `frontend/AGENTS.md` § "UI/UX Component Sourcing".
 */
export { PageHeading, default as PageHeadingDefault } from "./page-heading";
export { EmptyState, PageShell } from "./page-shell";
