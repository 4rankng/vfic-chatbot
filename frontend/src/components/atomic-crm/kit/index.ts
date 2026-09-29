/**
 * Shared console primitives for the TingHire recruiter console.
 *
 * These are the app-level building blocks every resource screen composes:
 * `PageShell` (page column), `PageHeading` (title/subtitle/actions),
 * `EmptyState`, the react-admin bound form controls (`Form*`) and the
 * react-admin bound list surface (`ListTable`, `ListPagination`). They render on
 * Untitled UI anatomy and the console's own `--fs-*` role tokens, so a change
 * here moves every route.
 *
 * Design rationale: `frontend/AGENTS.md` § "UI/UX Component Sourcing".
 */
export { PageHeading, default as PageHeadingDefault } from "./page-heading";
export { EmptyState, PageShell } from "./page-shell";
export {
  FormCheckbox,
  FormSelect,
  FormTextArea,
  FormTextInput,
  FormToggle,
  type FormChoice,
} from "./form-controls";
export {
  ListPagination,
  ListTable,
  type ListTableClassNames,
  type ListTableColumn,
} from "./list-table";
