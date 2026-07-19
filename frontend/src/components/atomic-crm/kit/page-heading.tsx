import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Page heading with optional subtitle and right-aligned actions.
 *
 * Adapted from Tailkit `a-c-page-headings-03` (With Actions). Purely
 * presentational — callers own title/subtitle text and action buttons.
 *
 * Layout: title+subtitle on the left, actions on the right, separated from
 * the page body by a hairline border-bottom. Stacks vertically under `sm`.
 *
 * Consume via `--tt-*` tokens (see conversations/inbox/tokens.css).
 */
type PageHeadingProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  /** Wrap the row in a border-bottom hairline (default: true). */
  bordered?: boolean;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
};

export function PageHeading({
  title,
  subtitle,
  eyebrow,
  actions,
  bordered = true,
  className,
  bodyClassName,
  children,
}: PageHeadingProps) {
  const hasActions = Boolean(actions);
  return (
    <div className={cn("tt-page-heading", className)}>
      <div
        className={cn(
          "tt-page-heading-row flex flex-col gap-3 pb-4 sm:flex-row sm:items-center sm:justify-between",
          bordered &&
            "border-b border-[var(--tt-border)] sm:mb-6 sm:border-b-[1.5px]",
        )}
      >
        <div className="tt-page-heading-copy min-w-0">
          {eyebrow ? (
            <p className="tt-page-heading-eyebrow text-[length:var(--text-caption)] font-semibold uppercase tracking-[0.08em] text-[var(--tt-ink-muted)]">
              {eyebrow}
            </p>
          ) : null}
          <h1 className="tt-page-heading-title text-[length:var(--text-page-title)] font-bold leading-tight text-[var(--tt-ink)]">
            {title}
          </h1>
          {subtitle ? (
            <p className="tt-page-heading-subtitle mt-1 text-[length:var(--text-body)] text-[var(--tt-ink-muted)]">
              {subtitle}
            </p>
          ) : null}
        </div>
        {hasActions ? (
          <div className="tt-page-heading-actions flex flex-wrap items-center justify-start gap-2 [&_button]:min-h-11 [&_a]:min-h-11 sm:justify-end md:[&_button]:min-h-8 md:[&_a]:min-h-8">
            {actions}
          </div>
        ) : null}
      </div>
      {children ? (
        <div className={cn("tt-page-heading-body", bodyClassName)}>
          {children}
        </div>
      ) : null}
    </div>
  );
}

export default PageHeading;
