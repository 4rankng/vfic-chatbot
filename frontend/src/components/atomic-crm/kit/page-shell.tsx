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
        "mx-auto flex w-full flex-col gap-5 px-4 py-5 md:px-6 md:py-6 lg:px-8",
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
};

/**
 * The console's single empty state, rendered on Untitled UI's empty-state
 * anatomy. Every surface that can be empty routes through here — knowledge
 * base, automation, knowledge, personas, projects and conversations — so the
 * icon frame, type scale and action placement move together.
 *
 * The icon stays a caller-supplied element (callers pass a sized lucide icon)
 * inside a console-token circle, so this does not force a shipped component
 * signature change on six screens.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <UntitledEmptyState
      size="md"
      className={cx(
        "min-h-56 gap-4 rounded-xl border border-secondary bg-primary px-6 py-10",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="flex size-12 items-center justify-center rounded-full bg-secondary text-fg-quaternary [&>svg]:size-5"
      >
        {icon}
      </span>
      <UntitledEmptyState.Content className="gap-1">
        <UntitledEmptyState.Title className="text-section-title font-semibold text-primary [&]:!text-[length:var(--fs-section-title)]">
          {title}
        </UntitledEmptyState.Title>
        <UntitledEmptyState.Description className="max-w-sm text-body-sm text-tertiary">
          {description}
        </UntitledEmptyState.Description>
      </UntitledEmptyState.Content>
      {action ? (
        <UntitledEmptyState.Footer className="mt-1 flex items-center justify-center gap-3">
          {action}
        </UntitledEmptyState.Footer>
      ) : null}
    </UntitledEmptyState>
  );
}
