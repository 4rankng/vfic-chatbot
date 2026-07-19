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
        "tt-page-shell mx-auto w-full px-4 py-5 pb-24 md:px-6 md:py-7 md:pb-8 lg:px-8",
        PAGE_WIDTHS[size],
        className,
      )}
    >
      {children}
    </div>
  );
}

type AlternateCardProps = {
  children: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
  bodyClassName?: string;
};

/** Tailkit alternate-card anatomy adapted from a-c-form-layouts-04/05. */
export function AlternateCard({
  children,
  title,
  description,
  icon,
  action,
  className,
  bodyClassName,
}: AlternateCardProps) {
  const hasHeader = Boolean(title || description || icon || action);

  return (
    <section
      className={cn(
        "tt-alternate-card rounded-xl bg-[var(--tt-surface-muted)] p-2 ring-1 ring-[var(--tt-border)]",
        className,
      )}
    >
      {hasHeader ? (
        <header className="flex min-h-14 items-center justify-between gap-3 px-3 py-2 sm:px-4">
          <div className="flex min-w-0 items-start gap-2.5">
            {icon ? (
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-[var(--tt-accent-soft)] text-[var(--tt-accent-strong)]">
                {icon}
              </span>
            ) : null}
            <div className="min-w-0">
              {title ? (
                <h2 className="text-[length:var(--text-section-title)] font-semibold leading-tight text-[var(--tt-ink)]">
                  {title}
                </h2>
              ) : null}
              {description ? (
                <p className="mt-0.5 text-[length:var(--text-body-sm)] leading-5 text-[var(--tt-ink-muted)]">
                  {description}
                </p>
              ) : null}
            </div>
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </header>
      ) : null}
      <div
        className={cn(
          "rounded-lg border border-[var(--tt-border)] bg-[var(--tt-surface-lift)] shadow-[var(--tt-shadow-xs)]",
          bodyClassName,
        )}
      >
        {children}
      </div>
    </section>
  );
}

type EmptyStateProps = {
  icon: ReactNode;
  title: ReactNode;
  description: ReactNode;
  action?: ReactNode;
  className?: string;
};

/** Tailkit a-c-empty-states-03 adapted to Ting Ting tokens. */
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
