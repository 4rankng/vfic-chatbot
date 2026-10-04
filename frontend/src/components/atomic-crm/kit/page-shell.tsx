import type { ReactNode } from "react";

import { EmptyState as UntitledEmptyState } from "@/components/application/empty-state/empty-state";
import { cx } from "@/utils/cx";

type PageShellProps = {
  children: ReactNode;
  className?: string;
  size?: "default" | "narrow" | "wide";
};

const PAGE_WIDTHS = {
  default: "max-w-[1180px]",
  narrow: "max-w-3xl",
  wide: "max-w-[1440px]",
} as const;

/**
 * Standard page column for a resource screen: one centred width, one vertical
 * rhythm. The scrolling region belongs to the app shell
 * (`.workspace-frame-content`), so this only lays out content.
 */
export function PageShell({
  children,
  className,
  size = "default",
}: PageShellProps) {
  return (
    <div
      className={cx(
        "mx-auto flex w-full min-w-0 flex-col gap-5 px-4 py-5 md:px-6 md:py-6 lg:px-8",
        PAGE_WIDTHS[size],
        className,
      )}
    >
      {children}
    </div>
  );
}

type EmptyStateProps = {
  icon: ReactNode;
  title: ReactNode;
  description: ReactNode;
  action?: ReactNode;
  className?: string;
  role?: "status" | "alert";
  variant?: "panel" | "inline";
};

/**
 * The console's single empty state, rendered on Untitled UI's empty-state
 * anatomy. Every surface that can be empty routes through here — knowledge
 * base, automation, knowledge, projects and conversations — so the
 * icon treatment, type scale and action placement move together.
 *
 * The icon stays a caller-supplied element (callers pass a sized lucide icon)
 * without a decorative frame, so this does not force a shipped component
 * signature change on six screens.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  role = "status",
  variant = "panel",
}: EmptyStateProps) {
  return (
    <UntitledEmptyState
      size="md"
      role={role}
      className={cx(
        "uu-scope min-w-0 gap-4 px-4 text-center sm:px-6",
        variant === "panel"
          ? "min-h-56 rounded-panel border border-secondary bg-primary py-8 sm:py-10"
          : "min-h-44 py-6",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="flex size-12 items-center justify-center text-fg-quaternary [&>svg]:size-5"
      >
        {icon}
      </span>
      <div className="grid min-w-0 max-w-sm gap-2">
        <h2 className="text-section-title font-semibold text-foreground [overflow-wrap:anywhere]">
          {title}
        </h2>
        <UntitledEmptyState.Description className="max-w-sm text-body-sm text-tertiary [overflow-wrap:anywhere]">
          {description}
        </UntitledEmptyState.Description>
      </div>
      {action ? (
        <UntitledEmptyState.Footer className="mt-1 flex flex-wrap items-center justify-center gap-3">
          {action}
        </UntitledEmptyState.Footer>
      ) : null}
    </UntitledEmptyState>
  );
}
