import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, useHref, useLocation } from "react-router";
import { Menu } from "lucide-react";

import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Tooltip } from "@/components/base/tooltip/tooltip";
import { NavItemBase } from "@/components/application/app-navigation/base-components/nav-item";
import { SlideoutMenu } from "@/components/application/slideout-menus/slideout-menu";
import { cx } from "@/utils/cx";

import { useCompiledRuntime } from "../capabilities/runtime-context";
import { useRoleActions } from "../hooks/useRoleActions";
import { AccountMenu } from "./topbar/account-menu";
import { CommandPalette } from "./topbar/command-palette";
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
import "./workspace-mobile-chat.css";

type WorkspaceShellProps = {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
};

/** Single destination row: icon-only in the rail, labelled in the drawer. */
const DestinationItem = ({
  destination,
  path,
  attentionCount,
  labelled,
  onNavigate,
}: {
  destination: WorkspaceDestination;
  path: string;
  attentionCount: number;
  labelled: boolean;
  onNavigate?: () => void;
}) => {
  const href = useHref(getWorkspaceDestination(destination, attentionCount));
  const showBadge = destination.id === "messages" && attentionCount > 0;

  const item = (
    <NavItemBase
      type="link"
      href={href}
      icon={destination.Icon}
      current={destination.isActive(path)}
      onClick={onNavigate}
      badge={
        showBadge && labelled ? (
          <Badge size="sm" type="pill-color" color="error">
            {attentionCount > 99 ? "99+" : attentionCount}
          </Badge>
        ) : undefined
      }
    >
      {labelled ? (
        destination.label
      ) : (
        <span className="sr-only">{destination.label}</span>
      )}
    </NavItemBase>
  );

  if (labelled) return item;

  return (
    <Tooltip title={destination.label} placement="right">
      {item}
    </Tooltip>
  );
};

const SidebarSections = ({
  sections,
  path,
  attentionCount,
  labelled,
  onNavigate,
}: {
  sections: readonly WorkspaceSection[];
  path: string;
  attentionCount: number;
  labelled: boolean;
  onNavigate?: () => void;
}) => (
  <>
    {sections.map((section) => (
      <div key={section.id}>
        {labelled ? (
          <p className="px-4 pt-4 pb-1 text-xs font-bold text-quaternary uppercase">
            {section.label}
          </p>
        ) : null}
        <ul className={labelled ? "px-2 pb-1" : "px-2.5 pb-1"}>
          {section.items.map((destination) => (
            <li key={destination.id} className="py-0.5">
              <DestinationItem
                destination={destination}
                path={path}
                attentionCount={attentionCount}
                labelled={labelled}
                onNavigate={onNavigate}
              />
            </li>
          ))}
        </ul>
      </div>
    ))}
  </>
);

const BrandMark = ({ className }: { className?: string }) => (
  <Link
    to="/"
    className={cx(
      "flex size-10 items-center justify-center rounded-xl outline-focus-ring focus-visible:outline-2 focus-visible:outline-offset-2",
      className,
    )}
    aria-label="TingHire — về trang tổng quan"
  >
    <img
      src="/brand/tinghire-icon-rail.png"
      alt=""
      aria-hidden="true"
      className="h-9 w-auto"
    />
  </Link>
);

/**
 * The authenticated application frame, matching the console's shell: a
 * full-width ink topbar carrying the brand, the notification bell and the
 * account menu; an icon-first ink rail below it; and the workspace canvas as a
 * rounded inset beside them.
 *
 * Below the rail breakpoint the same navigation moves into a React Aria
 * slideout, so no Radix subtree is ever nested inside a React Aria one.
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
        ".dashboard-center-panel, .knowledge-center-panel, .settings-center-panel, .profile-center-panel, .project-center-panel",
      )
      .forEach((panel) => {
        panel.scrollTop = 0;
      });
  }, [routeValue]);

  return (
    <div className={cx("workspace-frame", className)}>
      <a
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-[var(--workspace-paper)] focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-[var(--workspace-shell)]"
        href="#main-content"
        onClick={(event) => {
          // This application uses hash routes. Letting the fragment navigate
          // would open a missing route instead of moving keyboard focus.
          event.preventDefault();
          contentRef.current?.focus({ preventScroll: true });
          contentRef.current?.scrollIntoView({ block: "start" });
        }}
      >
        Bỏ qua điều hướng
      </a>

      <header className="uu-scope workspace-chrome workspace-topbar flex h-14 shrink-0 items-center gap-2 bg-primary px-3 lg:px-4">
        <SlideoutMenu.Trigger
          isOpen={isDrawerOpen}
          onOpenChange={setIsDrawerOpen}
        >
          <Button
            color="tertiary"
            size="md"
            iconLeading={Menu}
            aria-label="Mở điều hướng"
            className="rounded-lg lg:hidden"
          />
          <SlideoutMenu
            dialogClassName="uu-scope"
            // The width belongs on the panel: it is the box anchored to the
            // viewport edge, so the drawer sits flush right with no strip of
            // scrim showing beside it.
            panelClassName="uu-scope w-72 max-w-[85vw]"
          >
            {({ close }) => (
              <>
                <SlideoutMenu.Header
                  onClose={close}
                  className="border-b border-secondary"
                >
                  <span className="text-md font-semibold text-primary">
                    TingHire
                  </span>
                </SlideoutMenu.Header>
                <SlideoutMenu.Content className="gap-0 px-0">
                  <nav aria-label="Điều hướng chính">
                    <SidebarSections
                      sections={sections}
                      path={path}
                      attentionCount={attentionCount}
                      labelled
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

        <BrandMark className="hidden lg:flex lg:w-[72px]" />

        <div className="ml-auto flex items-center gap-1.5">
          <CommandPalette />
          <NotificationsMenu count={attentionCount} />
          <AccountMenu variant="topbar" />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="uu-scope workspace-chrome workspace-sidebar hidden shrink-0 flex-col bg-primary lg:flex lg:w-[72px]">
          <nav
            aria-label="Lối tắt không gian làm việc"
            className="flex-1 overflow-y-auto pt-2"
          >
            <SidebarSections
              sections={sections}
              path={path}
              attentionCount={attentionCount}
              labelled={false}
            />
          </nav>
        </aside>

        <main
          ref={contentRef}
          id="main-content"
          tabIndex={-1}
          className={cx("workspace-frame-content", contentClassName)}
        >
          {children}
        </main>
      </div>
    </div>
  );
};
