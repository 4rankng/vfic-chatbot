import type { ReactNode } from "react";

import { cx } from "@/utils/cx";

/**
 * Page heading with an optional eyebrow, subtitle and right-aligned actions.
 *
 * Untitled UI's application page-header anatomy: a title block on the left and
 * an action cluster on the right, separated from the body by a hairline. The
 * type comes from the console's role tokens (`--fs-*`), so it steps down on
 * mobile with the rest of the app instead of carrying its own sizes.
 *
 * Purely presentational — callers own title/subtitle text and action buttons.
 */
type PageHeadingProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  /** Slot above the title, e.g. a breadcrumb trail. */
  breadcrumbs?: ReactNode;
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
  breadcrumbs,
  actions,
  bordered = true,
  className,
  bodyClassName,
  children,
}: PageHeadingProps) {
  return (
    <div className={cx("w-full", className)}>
      {breadcrumbs ? <div className="pb-3">{breadcrumbs}</div> : null}
      <div
        className={cx(
          "flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between",
          bordered && "border-b border-secondary pb-4 sm:mb-5",
        )}
      >
        <div className="min-w-0">
          {eyebrow ? (
            <p className="text-caption font-semibold text-quaternary uppercase">
              {eyebrow}
            </p>
          ) : null}
          {/* `text-foreground` (console ink) not `text-primary`: inside an
              ancestor `.uu-scope` the latter resolves to the library's blue
              primary, so the same heading rendered two colours. */}
          <h1 className="text-page-title font-bold text-foreground">{title}</h1>
          {subtitle ? (
            <p className="mt-1 text-body text-tertiary">{subtitle}</p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center justify-start gap-2 [&_a]:min-h-11 [&_button]:min-h-11 sm:justify-end md:[&_a]:min-h-9 md:[&_button]:min-h-9">
            {actions}
          </div>
        ) : null}
      </div>
      {children ? <div className={bodyClassName}>{children}</div> : null}
    </div>
  );
}

export default PageHeading;
