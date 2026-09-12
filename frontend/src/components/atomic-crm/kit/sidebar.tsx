import type { ComponentType, ReactNode } from "react";
import { Link } from "react-router";

import { cn } from "@/lib/utils";

/**
 * Dark sidebar application shell — mini icon rail + expanded navigation panel.
 *
 * Adapted from Tailkit `a-l-dark-sidebar-06` (With Mini Sidebar). The mini
 * rail (56px) shows brand mark + primary icon shortcuts; the expanded panel
 * (280px) shows full labels, section headings, and badges. Both are dark
 * slate surfaces per the Tailkit visual direction.
 *
 * PURELY PRESENTATIONAL: the caller owns destinations, active-state logic,
 * badge counts, and routing. This component renders nothing but chrome —
 * no React Admin, no TanStack Query, no Socket.IO.
 *
 * Consume via `--tt-*` tokens (slate sidebar + teal accent).
 */

export type KitSidebarDestination = {
  id: string;
  label: string;
  to: string;
  Icon: ComponentType<{ className?: string }>;
  isActive: (path: string) => boolean;
  /** Optional numeric badge (e.g. unread count). */
  badge?: number;
  /** Render the icon in the mini rail (default: true). */
  showInRail?: boolean;
};

export type KitSidebarSection = {
  id: string;
  /** Section heading, e.g. "Dự án", "Tài khoản". Omit for an unlabeled group. */
  label?: string;
  destinations: ReadonlyArray<KitSidebarDestination>;
};

type SidebarLinkProps = {
  destination: KitSidebarDestination;
  path: string;
  expanded: boolean;
};

function badgeLabel(count: number): string {
  return count > 99 ? "99+" : String(count);
}

function SidebarLink({ destination, path, expanded }: SidebarLinkProps) {
  const active = destination.isActive(path);
  const { Icon, label, to, badge } = destination;
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      title={expanded ? undefined : label}
      className={cn(
        "tt-sidebar-link group flex items-center gap-2.5 rounded-lg border px-2.5 text-[length:var(--text-nav)] font-medium transition-colors duration-[var(--tt-motion-fast)]",
        expanded ? "py-2" : "h-10 justify-center px-0",
        active
          ? "border-[var(--tt-sidebar-accent)] bg-[var(--tt-sidebar-accent-soft)] text-[var(--tt-sidebar-ink)]"
          : "border-transparent text-[var(--tt-sidebar-ink-muted)] hover:bg-[var(--tt-sidebar-hover)] hover:text-[var(--tt-sidebar-ink)]",
      )}
    >
      <span
        className={cn(
          "tt-sidebar-link-icon flex flex-none items-center",
          active
            ? "text-[var(--tt-sidebar-accent)]"
            : "text-[var(--tt-sidebar-ink-muted)] group-hover:text-[var(--tt-sidebar-ink)]",
          expanded ? "" : "mx-auto",
        )}
        aria-hidden="true"
      >
        <Icon className="size-5" />
      </span>
      {expanded ? <span className="min-w-0 grow truncate">{label}</span> : null}
      {expanded && badge !== undefined && badge > 0 ? (
        <span
          className={cn(
            "tt-sidebar-link-badge inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[length:var(--text-badge)] font-semibold",
            active
              ? "bg-[var(--tt-sidebar-accent)] text-[var(--tt-sidebar)]"
              : "bg-[var(--tt-sidebar-accent)]/85 text-white",
          )}
        >
          {badgeLabel(badge)}
        </span>
      ) : null}
      {!expanded && badge !== undefined && badge > 0 ? (
        <span
          aria-label={`${badge} thông báo`}
          className="tt-sidebar-rail-badge absolute right-2 top-1.5 size-2 rounded-full bg-[var(--tt-sidebar-accent)] ring-2 ring-[var(--tt-sidebar)]"
        />
      ) : null}
    </Link>
  );
}

type MiniRailLinkProps = {
  destination: KitSidebarDestination;
  path: string;
};

function MiniRailLink({ destination, path }: MiniRailLinkProps) {
  return (
    <span className="relative block">
      <SidebarLink destination={destination} path={path} expanded={false} />
    </span>
  );
}

type KitSidebarProps = {
  /** Brand mark / logo rendered at the top of the mini rail. */
  brand: ReactNode;
  /** Brand block rendered at the top of the expanded panel (e.g. app name). */
  brandLabel?: ReactNode;
  /** Grouped destinations rendered in both rail (icons) and panel (full). */
  sections: ReadonlyArray<KitSidebarSection>;
  /** Footer destinations (settings, account, logout) — rendered bottom of both. */
  footerSections?: ReadonlyArray<KitSidebarSection>;
  /** Current normalized path used for active-state detection. */
  path: string;
  /** Accessible label for the sidebar nav element. */
  ariaLabel?: string;
  className?: string;
};

export function KitSidebar({
  brand,
  brandLabel,
  sections,
  footerSections,
  path,
  ariaLabel = "Điều hướng chính",
  className,
}: KitSidebarProps) {
  return (
    <aside
      aria-label={ariaLabel}
      className={cn(
        "tt-sidebar fixed inset-y-0 left-0 z-50 flex h-full w-72 flex-col border-r border-[var(--tt-sidebar-border)] bg-[var(--tt-sidebar)] pl-14 text-[var(--tt-sidebar-ink)]",
        className,
      )}
    >
      {/* Mini icon rail */}
      <div className="tt-sidebar-rail absolute inset-y-0 left-0 z-10 flex w-14 flex-col border-r border-[var(--tt-sidebar-border)] bg-black/20">
        <div className="flex-none">{brand}</div>
        <nav
          aria-label="Lối tắt"
          className="flex grow flex-col items-stretch gap-1 px-2 py-3"
        >
          {sections
            .flatMap((section) => section.destinations)
            .map((destination) =>
              destination.showInRail === false ? null : (
                <MiniRailLink
                  key={`rail-${destination.id}`}
                  destination={destination}
                  path={path}
                />
              ),
            )}
        </nav>
        {footerSections && footerSections.length > 0 ? (
          <nav
            aria-label="Lối tắt tài khoản"
            className="flex flex-none flex-col items-stretch gap-1 px-2 py-3"
          >
            {footerSections
              .flatMap((section) => section.destinations)
              .map((destination) =>
                destination.showInRail === false ? null : (
                  <MiniRailLink
                    key={`rail-${destination.id}`}
                    destination={destination}
                    path={path}
                  />
                ),
              )}
          </nav>
        ) : null}
      </div>

      {/* Expanded panel */}
      <div className="tt-sidebar-panel flex h-full flex-col overflow-y-auto">
        {brandLabel ? (
          <div className="tt-sidebar-brand-row flex h-14 flex-none items-center px-4">
            <span className="truncate text-[length:var(--text-card-title)] font-bold tracking-wide text-[var(--tt-sidebar-ink)]">
              {brandLabel}
            </span>
          </div>
        ) : null}
        <div className="flex-1 px-3 pb-4">
          {sections.map((section, sIdx) => (
            <div key={section.id} className={cn(sIdx > 0 && "mt-5")}>
              {section.label ? (
                <div className="px-3 pb-1 pt-2 text-[length:var(--text-caption)] font-semibold uppercase tracking-wider text-[var(--tt-sidebar-ink-muted)]">
                  {section.label}
                </div>
              ) : null}
              <nav className="space-y-0.5">
                {section.destinations.map((destination) => (
                  <SidebarLink
                    key={destination.id}
                    destination={destination}
                    path={path}
                    expanded
                  />
                ))}
              </nav>
            </div>
          ))}
        </div>
        {footerSections && footerSections.length > 0 ? (
          <div className="flex-none border-t border-[var(--tt-sidebar-border)] px-3 py-3">
            {footerSections.map((section) => (
              <nav key={section.id} className="space-y-0.5">
                {section.destinations.map((destination) => (
                  <SidebarLink
                    key={destination.id}
                    destination={destination}
                    path={path}
                    expanded
                  />
                ))}
              </nav>
            ))}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

export default KitSidebar;
