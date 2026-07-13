import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { MoreHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

import { useRoleActions } from "../hooks/useRoleActions";
import { useNotifications } from "./topbar/useNotifications";
import "./mobile-workspace.css";
import Header from "./Header";
import {
  getWorkspaceDestinations,
  getWorkspaceOverflowDestinations,
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
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const location = useLocation();
  const { isAdmin } = useRoleActions();
  const role = isAdmin ? "admin" : "recruiter";
  const routeValue =
    location.pathname === "/" && location.hash.startsWith("#/")
      ? location.hash
      : `${location.pathname}${location.search}`;
  const path = normalizeWorkspacePath(routeValue);
  const destinations = getWorkspaceDestinations(role, surface);
  const overflowDestinations =
    surface === "mobile" ? getWorkspaceOverflowDestinations(role) : [];
  const isOverflowActive = overflowDestinations.some(({ isActive }) =>
    isActive(path),
  );

  return (
    <nav
      aria-label={
        surface === "mobile"
          ? "Điều hướng chính"
          : "Lối tắt không gian làm việc"
      }
      className={cn(
        "workspace-navigation",
        surface === "mobile"
          ? "workspace-navigation-mobile"
          : "workspace-navigation-rail",
      )}
    >
      <div
        className={cn(
          "workspace-navigation-items",
          overflowDestinations.length > 0 &&
            "workspace-navigation-items--with-overflow",
        )}
      >
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
        {overflowDestinations.length > 0 ? (
          <Sheet open={isMoreOpen} onOpenChange={setIsMoreOpen}>
            <SheetTrigger asChild>
              <button
                type="button"
                aria-label="Mở thêm mục điều hướng"
                aria-pressed={isMoreOpen}
                className={cn(
                  "workspace-navigation-link",
                  "workspace-navigation-more",
                  isOverflowActive && "is-active",
                )}
              >
                <span className="workspace-navigation-icon" aria-hidden="true">
                  <MoreHorizontal />
                </span>
                <span className="workspace-navigation-label">Thêm</span>
              </button>
            </SheetTrigger>
            <SheetContent side="bottom" className="mobile-nav-more-sheet">
              <SheetTitle className="mobile-nav-more-title">Thêm</SheetTitle>
              <div className="mobile-nav-more-items">
                {overflowDestinations.map(
                  ({ id, label, to, Icon, isActive }) => (
                    <SheetClose asChild key={id}>
                      <Link
                        to={to}
                        aria-current={isActive(path) ? "page" : undefined}
                        className={cn(
                          "mobile-nav-more-link",
                          isActive(path) && "is-active",
                        )}
                      >
                        <Icon aria-hidden="true" />
                        <span>{label}</span>
                      </Link>
                    </SheetClose>
                  ),
                )}
              </div>
            </SheetContent>
          </Sheet>
        ) : null}
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
  const contentRef = useRef<HTMLElement>(null);
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

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;

    content.scrollTop = 0;
    content
      .querySelectorAll<HTMLElement>(
        ".dashboard-center-panel, .knowledge-center-panel, .settings-center-panel, .profile-center-panel, .persona-center-panel, .project-center-panel",
      )
      .forEach((panel) => {
        panel.scrollTop = 0;
      });
  }, [routeValue]);

  return (
    <div className={cn("workspace-frame", className)}>
      <a className="workspace-skip-link" href="#main-content">
        Bỏ qua điều hướng
      </a>
      <Header />
      <WorkspaceNavigation surface="rail" attentionCount={attentionCount} />
      <main
        ref={contentRef}
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
