import { useHref } from "react-router";
import { Link as AriaLink } from "react-aria-components";

import { cx } from "@/utils/cx";

import {
  getWorkspaceDestination,
  type WorkspaceDestination,
} from "./workspace-nav-model";

/**
 * One bottom-tab destination: a 48px-tall icon-over-label link with the
 * console's touch styling. The active tab carries `aria-current="page"`; the
 * 3px top indicator and the brand ink come from `.workspace-tabbar` rules in
 * `src/index.css`, so the geometry stays with the rest of the shell tokens.
 */
const MobileTabItem = ({
  destination,
  path,
  attentionCount,
}: {
  destination: WorkspaceDestination;
  path: string;
  attentionCount: number;
}) => {
  // Same href contract as the rail's DestinationItem: the router resolves
  // the destination to a hash href, needs_attention filter included.
  const href = useHref(getWorkspaceDestination(destination, attentionCount));
  const current = destination.isActive(path);
  const showBadge = destination.id === "messages" && attentionCount > 0;
  const Icon = destination.Icon;

  return (
    <AriaLink
      href={href}
      aria-current={current ? "page" : undefined}
      aria-label={
        showBadge
          ? `${destination.label}, ${attentionCount > 99 ? "99+" : attentionCount} tin chưa đọc`
          : undefined
      }
      className="workspace-tabbar-item"
    >
      <span className="workspace-tabbar-icon">
        {Icon ? <Icon aria-hidden="true" className="size-5" /> : null}
        {showBadge ? (
          <span aria-hidden="true" className="workspace-tabbar-badge">
            {attentionCount > 99 ? "99+" : attentionCount}
          </span>
        ) : null}
      </span>
      <span className="workspace-tabbar-label">{destination.label}</span>
    </AriaLink>
  );
};

type MobileTabBarProps = {
  /** Primary destinations, already capped at `MOBILE_TAB_LIMIT`. */
  tabs: readonly WorkspaceDestination[];
  /** Normalized current path, shared with the rail's active-state logic. */
  path: string;
  /** Unread reply count; only the inbox tab badges with it. */
  attentionCount: number;
  className?: string;
};

/**
 * The phone-width primary navigation: a fixed bottom tab bar (`< md`). The
 * desktop rail and the slideout drawer stay exactly as they are — this bar
 * only ever renders below 768px, where the drawer alone hid the main
 * destinations behind a hamburger. The full destination list (including
 * whatever falls past the tab limit) remains in the drawer.
 */
export const MobileTabBar = ({
  tabs,
  path,
  attentionCount,
  className,
}: MobileTabBarProps) => (
  <nav
    aria-label="Điều hướng chính"
    className={cx("workspace-tabbar md:hidden", className)}
  >
    <ul className="workspace-tabbar-list">
      {tabs.map((destination) => (
        <li key={destination.id} className="workspace-tabbar-tab">
          <MobileTabItem
            destination={destination}
            path={path}
            attentionCount={attentionCount}
          />
        </li>
      ))}
    </ul>
  </nav>
);
