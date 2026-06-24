import { memo } from "react";
import { Link } from "react-router";

interface NavPillProps {
  label: string;
  to: string;
  isActive: boolean;
}

/**
 * Segmented pill nav item. A soft active highlight plus a brand dot reads
 * cleanly on the frosted glass topbar. Replaces the old underline-style tab.
 * Memoized: all props are primitives (string, string, boolean) so React.memo
 * short-circuits re-renders when the active route is unchanged.
 */
export const NavPill = memo(({ label, to, isActive }: NavPillProps) => (
  <Link
    to={to}
    className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition-colors ${
      isActive
        ? "bg-muted/70 text-foreground shadow-sm dark:bg-muted/40"
        : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
    }`}
  >
    <span
      className={`h-1.5 w-1.5 rounded-full transition-colors ${
        isActive ? "bg-primary" : "bg-transparent"
      }`}
    />
    {label}
  </Link>
));
