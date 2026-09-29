import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, useHref, useLocation } from "react-router";
import { Menu } from "lucide-react";

import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { NavItemBase } from "@/components/application/app-navigation/base-components/nav-item";
import { SlideoutMenu } from "@/components/application/slideout-menus/slideout-menu";

import { useCompiledRuntime } from "../capabilities/runtime-context";
import { useRoleActions } from "../hooks/useRoleActions";
import { AccountMenu } from "./topbar/account-menu";
import { NotificationsMenu } from "./topbar/notifications-menu";
import { useNotifications } from "./topbar/useNotifications";
import {
  getWorkspaceDestination,
  getWorkspaceSections,
  normalizeWorkspacePath,
  type WorkspaceDestination,
  type WorkspaceRole,
  type WorkspaceSection,
} from "./workspace-nav-model";

type WorkspaceShellProps = {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
};

const SIDEBAR_WIDTH = "264px";

/** Single destination row; resolves the hash-router href and the inbox badge. */
const DestinationItem = ({
  destination,
  path,
  attentionCount,
  onNavigate,
}: {
  destination: WorkspaceDestination;
  path: string;
  attentionCount: number;
  onNavigate?: () => void;
}) => {
  const href = useHref(getWorkspaceDestination(destination, attentionCount));
  const showBadge = destination.id === "messages" && attentionCount > 0;

  return (
    <NavItemBase
      type="link"
      href={href}
      icon={destination.Icon}
      current={destination.isActive(path)}
      onClick={onNavigate}
      badge={
        showBadge ? (
          <Badge size="sm" type="pill-color" color="error">
            {attentionCount > 99 ? "99+" : attentionCount}
          </Badge>
        ) : undefined
      }
    >
      {destination.label}
    </NavItemBase>
  );
};

const SidebarSections = ({
  sections,
  path,
  attentionCount,
  onNavigate,
}: {
  sections: readonly WorkspaceSection[];
  path: string;
  attentionCount: number;
  onNavigate?: () => void;
}) => (
  <>
    {sections.map((section) => (
      <div key={section.id}>
        <p className="px-5 pt-5 pb-1 text-xs font-bold text-quaternary uppercase">
          {section.label}
        </p>
        <ul className="px-3 pb-1">
          {section.items.map((destination) => (
            <li key={destination.id} className="py-0.5">
              <DestinationItem
                destination={destination}
                path={path}
                attentionCount={attentionCount}
                onNavigate={onNavigate}
              />
            </li>
          ))}
        </ul>
      </div>
    ))}
  </>
);

const BrandMark = () => (
  <Link
    to="/"
    className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 outline-focus-ring focus-visible:outline-2 focus-visible:outline-offset-2"
    aria-label="TingHire — về trang tổng quan"
  >
    <img
      src="/brand/tinghire-icon-transparent.png"
      alt=""
      aria-hidden="true"
      className="size-7"
    />
    <span className="text-md font-semibold text-primary">TingHire</span>
  </Link>
);

/**
 * The authenticated application frame: a sectioned sidebar, a topbar carrying
 * notifications and the account menu, and — below the sidebar breakpoint — the
 * same navigation inside a React Aria slideout so no Radix subtree is nested in
 * a React Aria one.
 *
 * `.workspace-frame` stays the token root (every feature stylesheet reads
 * `--workspace-*` from it) and `.workspace-frame-content` stays the scrolling
 * main region the feature sheets size against.
 */
export const WorkspaceShell = ({
  children,
  className,
  contentClassName,
}: WorkspaceShellProps) => {
  const location = useLocation();
  const contentRef = useRef<HTMLElement>(null);
  const { count: attentionCount } = useNotifications();
  const { isAdmin } = useRoleActions();
  const { navigation } = useCompiledRuntime();
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const role: WorkspaceRole = isAdmin ? "admin" : "recruiter";
  const routeValue =
    location.pathname === "/" && location.hash.startsWith("#/")
      ? location.hash
      : `${location.pathname}${location.search}`;
  const path = normalizeWorkspacePath(routeValue);
  const sections = getWorkspaceSections(role, navigation);

  // A new route starts at the top of its own scroll container; feature panels
  // keep their own internal scroll position otherwise.
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
    <div className={`workspace-frame ${className ?? ""}`}>
      <a
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-primary focus:ring-1 focus:ring-secondary"
        href="#main-content"
      >
        Bỏ qua điều hướng
      </a>

      <aside
        className="workspace-sidebar uu-scope hidden border-r border-secondary bg-primary lg:fixed lg:inset-y-0 lg:left-0 lg:z-30 lg:flex lg:flex-col"
        style={{ width: SIDEBAR_WIDTH }}
      >
        <div className="flex h-16 shrink-0 items-center px-3">
          <BrandMark />
        </div>
        <nav aria-label="Điều hướng chính" className="flex-1 overflow-y-auto">
          <SidebarSections
            sections={sections}
            path={path}
            attentionCount={attentionCount}
          />
        </nav>
        <div className="shrink-0 border-t border-secondary p-3">
          <AccountMenu variant="sidebar" />
        </div>
      </aside>

      <div className="flex h-full min-h-0 flex-col lg:pl-[264px]">
        <header className="uu-scope sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b border-secondary bg-primary px-3 lg:h-16 lg:px-6">
          <SlideoutMenu.Trigger
            isOpen={isDrawerOpen}
            onOpenChange={setIsDrawerOpen}
          >
            <Button
              color="tertiary"
              size="sm"
              iconLeading={Menu}
              aria-label="Mở điều hướng"
              className="rounded-lg lg:hidden"
            />
            <SlideoutMenu dialogClassName="uu-scope w-72 max-w-[85vw]">
              {({ close }) => (
                <>
                  <SlideoutMenu.Header
                    onClose={close}
                    className="border-b border-secondary"
                  >
                    <BrandMark />
                  </SlideoutMenu.Header>
                  <SlideoutMenu.Content className="gap-0 px-0">
                    <nav aria-label="Điều hướng chính">
                      <SidebarSections
                        sections={sections}
                        path={path}
                        attentionCount={attentionCount}
                        onNavigate={close}
                      />
                    </nav>
                  </SlideoutMenu.Content>
                  <SlideoutMenu.Footer className="mt-auto">
                    <AccountMenu variant="sidebar" />
                  </SlideoutMenu.Footer>
                </>
              )}
            </SlideoutMenu>
          </SlideoutMenu.Trigger>

          <div className="ml-auto flex items-center gap-1.5">
            <NotificationsMenu count={attentionCount} />
            <span className="lg:hidden">
              <AccountMenu variant="topbar" />
            </span>
          </div>
        </header>

        <main
          ref={contentRef}
          id="main-content"
          className={`workspace-frame-content ${contentClassName ?? ""}`}
        >
          {children}
        </main>
      </div>
    </div>
  );
};
