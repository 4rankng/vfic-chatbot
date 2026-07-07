import { Bell, FileText, User, Users } from "lucide-react";
import { useTranslate, useUserMenu } from "ra-core";
import { Link, matchPath, useLocation } from "react-router";
import { useMemo } from "react";
import { ThemeModeToggle } from "@/components/admin/theme-mode-toggle";
import { UserMenu } from "@/components/admin/user-menu";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";

import { useConfigurationContext } from "../root/ConfigurationContext";
import { useNotifications } from "./topbar/useNotifications";

type NavPillProps = {
  label: string;
  to: string;
  isActive: boolean;
};

const NavPill = ({ label, to, isActive }: NavPillProps) => (
  <Link
    to={to}
    className={`rounded-full px-3 py-2 text-sm font-medium transition ${
      isActive
        ? "bg-primary text-primary-foreground"
        : "text-muted-foreground hover:bg-muted hover:text-foreground"
    }`}
  >
    {label}
  </Link>
);

const NotificationsBell = () => {
  const { count } = useNotifications();

  return (
    <Link
      to="/conversations"
      className="relative grid size-10 place-items-center rounded-full text-muted-foreground transition hover:bg-muted hover:text-foreground"
      aria-label={
        count > 0 ? `${count} conversations need attention` : "Notifications"
      }
    >
      <Bell className="size-5" />
      {count > 0 ? (
        <span className="absolute -right-0.5 -top-0.5 min-w-5 rounded-full bg-destructive px-1 text-center text-[11px] font-semibold leading-5 text-destructive-foreground">
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </Link>
  );
};

const Header = () => {
  const { title } = useConfigurationContext();
  const location = useLocation();
  const translate = useTranslate();

  const currentPath = useMemo<string | false>(() => {
    if (matchPath("/", location.pathname)) return "/";
    if (matchPath("/conversations/*", location.pathname))
      return "/conversations";
    if (matchPath("/projects/*", location.pathname)) return "/projects";
    if (matchPath("/knowledge_sources/*", location.pathname))
      return "/knowledge_sources";
    // Unmatched secondary routes (e.g. /settings, /profile, /users) leave no
    // pill highlighted, matching the prior behavior.
    return false;
  }, [location.pathname]);

  return (
    <div className="sticky top-0 z-40 px-4 pt-3 md:px-6 md:pt-4">
      <div className="mx-auto max-w-[1440px]">
        <header className="flex h-14 items-center justify-between gap-3 rounded-2xl border border-border/70 bg-white/70 px-3 shadow-[0_8px_30px_rgba(0,0,0,0.06)] backdrop-blur-xl dark:bg-card/60 md:px-4">
          {/* Brand */}
          <Link
            to="/"
            className="flex h-full shrink-0 items-center"
            aria-label={title}
          >
            <img
              src="/light-logo.png"
              alt={title}
              className="h-7 w-auto py-1 dark:hidden md:h-8"
            />
            <img
              src="/dark-logo.png"
              alt={title}
              className="hidden h-7 w-auto py-1 dark:block md:h-8"
            />
          </Link>

          {/* Pill nav */}
          <nav className="hidden flex-1 items-center justify-center gap-5 lg:gap-8 md:flex">
            <NavPill
              label={translate("ra.page.dashboard")}
              to="/"
              isActive={currentPath === "/"}
            />
            <NavPill
              label={translate("resources.conversations.name", {
                smart_count: 2,
              })}
              to="/conversations"
              isActive={currentPath === "/conversations"}
            />
            <NavPill
              label={translate("resources.projects.name", { smart_count: 2 })}
              to="/projects"
              isActive={currentPath === "/projects"}
            />
            <NavPill
              label={translate("resources.knowledge_sources.name", {
                smart_count: 2,
              })}
              to="/knowledge_sources"
              isActive={currentPath === "/knowledge_sources"}
            />
          </nav>

          {/* Actions */}
          <div className="flex items-center gap-1 md:gap-2">
            <NotificationsBell />
            <ThemeModeToggle />
            <UserMenu />
          </div>
        </header>
      </div>
    </div>
  );
};

export const UsersMenu = () => {
  const translate = useTranslate();
  const userMenuContext = useUserMenu();
  if (!userMenuContext) {
    throw new Error("<UsersMenu> must be used inside <UserMenu>");
  }
  return (
    <DropdownMenuItem asChild onClick={userMenuContext.onClose}>
      <Link to="/users" className="flex items-center gap-2">
        <Users />
        {translate("resources.users.name", { smart_count: 2 })}
      </Link>
    </DropdownMenuItem>
  );
};

export const ProfileMenu = () => {
  const translate = useTranslate();
  const userMenuContext = useUserMenu();
  if (!userMenuContext) {
    throw new Error("<ProfileMenu> must be used inside <UserMenu>");
  }
  return (
    <DropdownMenuItem asChild onClick={userMenuContext.onClose}>
      <Link to="/profile" className="flex items-center gap-2">
        <User />
        {translate("crm.profile.title")}
      </Link>
    </DropdownMenuItem>
  );
};

export const ChangelogMenuItem = () => {
  const translate = useTranslate();
  const userMenuContext = useUserMenu();
  if (!userMenuContext) {
    throw new Error("<ChangelogMenuItem> must be used inside <UserMenu>");
  }
  return (
    <DropdownMenuItem asChild onClick={userMenuContext.onClose}>
      <Link to="/changelog" className="flex items-center gap-2">
        <FileText />
        {translate("crm.changelog.title")}
      </Link>
    </DropdownMenuItem>
  );
};
export default Header;
