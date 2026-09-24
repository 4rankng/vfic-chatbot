import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

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

export function PageShell({
  children,
  className,
  size = "default",
}: PageShellProps) {
  return (
    <div
      className={cn(
        "tt-page-shell mx-auto h-full min-h-0 w-full overflow-y-auto overscroll-contain px-4 py-5 pb-24 md:px-6 md:py-7 md:pb-8 lg:px-8",
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

/** Tailkit a-c-empty-states-03 adapted to TingHire tokens. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center",
        className,
      )}
    >
      <span className="flex size-12 items-center justify-center rounded-full bg-[var(--tt-accent-soft)] text-[var(--tt-accent-strong)]">
        {icon}
      </span>
      <h3 className="mt-4 text-[length:var(--text-section-title)] font-semibold text-[var(--tt-ink)]">
        {title}
      </h3>
      <p className="mt-1 max-w-md text-[length:var(--text-body-sm)] leading-5 text-[var(--tt-ink-muted)]">
        {description}
      </p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
