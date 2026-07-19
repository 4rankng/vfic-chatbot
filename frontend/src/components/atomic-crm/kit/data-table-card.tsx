import type { ReactNode } from "react";
import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Card-wrapped table with optional integrated search and header actions.
 *
 * Adapted from Tailkit `a-c-tables-14` (In Card Alternate with Search) and
 * `a-c-tables-15` (with search AND actions). Purely presentational — the
 * caller owns the data fetching, filtering, and row rendering. This component
 * provides only the chrome: outer card, header (title + optional actions +
 * search input), scrollable body.
 *
 * Consume via `--tt-*` tokens.
 */
type DataTableCardProps = {
  /** Card heading, e.g. "Ứng viên nóng tuần này". */
  title?: ReactNode;
  /** Optional smaller description under the title. */
  description?: ReactNode;
  /** Right-aligned action buttons (e.g. Export, New). */
  actions?: ReactNode;
  /** Controlled search value. When undefined, the search box is hidden. */
  searchValue?: string;
  /** Search change handler. Presence of this prop enables the search box. */
  onSearchChange?: (next: string) => void;
  /** Search box placeholder. */
  searchPlaceholder?: string;
  /** Accessible label for the search input. */
  searchLabel?: string;
  /** Table column headers. Omit to render a borderless headerless table. */
  columns?: ReadonlyArray<ReactNode>;
  /** Row content — caller renders `<tr><td/>…</tr>` children. */
  children: ReactNode;
  /** Make the table body vertically scrollable at this height (CSS length). */
  bodyMaxHeight?: string;
  /** Optional footer slot (e.g. pagination). */
  footer?: ReactNode;
  className?: string;
  /** Dense padding variant for high-row-count tables. */
  dense?: boolean;
};

export function DataTableCard({
  title,
  description,
  actions,
  searchValue,
  onSearchChange,
  searchPlaceholder = "Tìm kiếm",
  searchLabel = "Tìm kiếm trong bảng",
  columns,
  children,
  bodyMaxHeight,
  footer,
  className,
  dense = false,
}: DataTableCardProps) {
  const showHeader = Boolean(title || description || actions);
  const showSearch = typeof onSearchChange === "function";
  const cellPadY = dense ? "py-2" : "py-3";
  const cellPadX = dense ? "px-3" : "px-4";

  return (
    <div
      className={cn(
        "tt-data-table-card overflow-hidden rounded-xl border border-[var(--tt-border)] bg-[var(--tt-surface-lift)] shadow-[var(--tt-shadow-xs)]",
        className,
      )}
    >
      {showHeader || showSearch ? (
        <div className="tt-data-table-card-header flex flex-col gap-3 border-b border-[var(--tt-border)] p-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div className="tt-data-table-card-title min-w-0">
            {title ? (
              <h2 className="text-[length:var(--text-section-title)] font-semibold text-[var(--tt-ink)]">
                {title}
              </h2>
            ) : null}
            {description ? (
              <p className="mt-0.5 text-[length:var(--text-body-sm)] text-[var(--tt-ink-muted)]">
                {description}
              </p>
            ) : null}
          </div>
          <div className="tt-data-table-card-controls flex flex-wrap items-center gap-2">
            {showSearch ? (
              <label className="tt-data-table-card-search relative inline-flex items-center">
                <span className="sr-only">{searchLabel}</span>
                <Search
                  className="pointer-events-none absolute left-2.5 size-4 text-[var(--tt-ink-faint)]"
                  aria-hidden="true"
                />
                <input
                  type="search"
                  className="tt-input h-9 w-full rounded-lg border border-[var(--tt-border)] bg-[var(--tt-canvas)] pl-8 pr-3 text-[length:var(--text-control)] text-[var(--tt-ink)] placeholder:text-[var(--tt-ink-faint)] focus:border-[var(--tt-accent)] focus:outline-none focus:ring-2 focus:ring-[color-mix(in_srgb,var(--tt-ring)_35%,transparent)] sm:w-56"
                  placeholder={searchPlaceholder}
                  aria-label={searchLabel}
                  value={searchValue ?? ""}
                  onChange={(e) => onSearchChange!(e.target.value)}
                />
              </label>
            ) : null}
            {actions}
          </div>
        </div>
      ) : null}

      <div
        className="tt-data-table-card-body overflow-x-auto"
        style={bodyMaxHeight ? { maxHeight: bodyMaxHeight } : undefined}
      >
        <table className="tt-data-table-card-table w-full border-collapse text-left">
          {columns && columns.length > 0 ? (
            <thead className="tt-data-table-card-thead sticky top-0 z-[1] bg-[var(--tt-surface-muted)]">
              <tr>
                {columns.map((col, i) => (
                  <th
                    key={i}
                    scope="col"
                    className={cn(
                      "border-b border-[var(--tt-border)] text-[length:var(--text-meta)] font-semibold uppercase tracking-wide text-[var(--tt-ink-muted)]",
                      cellPadX,
                      cellPadY,
                    )}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
          ) : null}
          <tbody className="tt-data-table-card-tbody divide-y divide-[var(--tt-border)]">
            {children}
          </tbody>
        </table>
      </div>

      {footer ? (
        <div className="tt-data-table-card-footer border-t border-[var(--tt-border)] p-3">
          {footer}
        </div>
      ) : null}
    </div>
  );
}

export default DataTableCard;
