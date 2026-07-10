import { type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import { cn } from "@/lib/utils";

import { useRoleActions } from "../hooks/useRoleActions";
import { useNotifications } from "./topbar/useNotifications";
import {
  getWorkspaceDestinations,
  normalizeWorkspacePath,
  type WorkspaceNavigationSurface,
} from "./workspace-navigation";

type WorkspaceFrameProps = {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
};

const WorkspaceNavigation = ({
  surface,
  attentionCount,
}: {
  surface: WorkspaceNavigationSurface;
  attentionCount: number;
}) => {
  const location = useLocation();
  const { isAdmin } = useRoleActions();
  const role = isAdmin ? "admin" : "recruiter";
  const routeValue =
    location.pathname === "/" && location.hash.startsWith("#/")
      ? location.hash
      : `${location.pathname}${location.search}`;
  const path = normalizeWorkspacePath(routeValue);
  const destinations = getWorkspaceDestinations(role, surface);

  return (
    <nav
      aria-label={
        surface === "mobile"
          ? "Điều hướng chính"
          : "Điều hướng không gian làm việc"
      }
      className={cn(
        "workspace-navigation",
        surface === "mobile"
          ? "workspace-navigation-mobile"
          : "workspace-navigation-desktop",
      )}
    >
      <div className="workspace-navigation-items">
        {destinations.map(({ id, label, to, Icon, isActive }) => {
          const active = isActive(path);
          const badge = id === "messages" ? attentionCount : 0;

          return (
            <Link
              key={id}
              to={to}
              aria-current={active ? "page" : undefined}
              className={cn(
                "workspace-navigation-link",
                id === "account" && "workspace-navigation-link--account",
                active && "is-active",
              )}
            >
              <span className="workspace-navigation-icon" aria-hidden="true">
                <Icon />
                {badge > 0 ? (
                  <span className="workspace-navigation-badge">
                    {badge > 99 ? "99+" : badge}
                  </span>
                ) : null}
              </span>
              <span className="workspace-navigation-label">{label}</span>
              {badge > 0 ? (
                <span className="sr-only">, {badge} tin nhắn cần chú ý</span>
              ) : null}
              <span className="workspace-navigation-tooltip" role="tooltip">
                {label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
};

export const WorkspaceFrame = ({
  children,
  className,
  contentClassName,
}: WorkspaceFrameProps) => {
  const location = useLocation();
  const { count: attentionCount } = useNotifications();
  const routeValue =
    location.pathname === "/" && location.hash.startsWith("#/")
      ? location.hash
      : `${location.pathname}${location.search}`;
  const normalizedPath = normalizeWorkspacePath(routeValue);
  const routeSearch = routeValue.includes("?")
    ? routeValue.slice(routeValue.indexOf("?"))
    : location.search;
  const isConversationDetail =
    normalizedPath.startsWith("/conversations") &&
    new URLSearchParams(routeSearch).has("id");

  return (
    <div className={cn("workspace-frame", className)}>
      <a className="workspace-skip-link" href="#main-content">
        Bỏ qua điều hướng
      </a>
      <WorkspaceNavigation surface="desktop" attentionCount={attentionCount} />
      <main
        id="main-content"
        className={cn("workspace-frame-content", contentClassName)}
      >
        {children}
      </main>
      {!isConversationDetail ? (
        <WorkspaceNavigation surface="mobile" attentionCount={attentionCount} />
      ) : null}
    </div>
  );
};
