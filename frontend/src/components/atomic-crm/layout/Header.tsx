import { FileText, User, Users } from "lucide-react";
import { usePermissions, useTranslate, useUserMenu } from "ra-core";
import { Link, matchPath, useLocation } from "react-router";
import { useMemo } from "react";
import { ThemeModeToggle } from "@/components/admin/theme-mode-toggle";
import { UserMenu } from "@/components/admin/user-menu";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";

import { useConfigurationContext } from "../root/ConfigurationContext";
import { ChangelogPage } from "../misc/ChangelogPage";
import { NavPill } from "./topbar/NavPills";
import { NotificationsBell } from "./topbar/NotificationsBell";

const Header = () => {
  const { title } = useConfigurationContext();
  const location = useLocation();
  const translate = useTranslate();
  const { permissions } = usePermissions();
  const isAdmin = permissions === "admin";

  const currentPath = useMemo<string | false>(() => {
    if (matchPath("/", location.pathname)) return "/";
    if (matchPath("/leads/*", location.pathname)) return "/leads";
    if (matchPath("/conversations/*", location.pathname))
      return "/conversations";
    if (matchPath("/projects/*", location.pathname)) return "/projects";
    if (matchPath("/knowledge_sources/*", location.pathname))
      return "/knowledge_sources";
    if (matchPath("/users/*", location.pathname)) return "/users";
    // Unmatched secondary routes (e.g. /settings, /profile, /users) leave no
    // pill highlighted, matching the prior behavior.
    return false;
  }, [location.pathname]);

  return (
    <div className="sticky top-0 z-40 px-4 pt-3 md:pt-4 lg:px-6">
      <div className="mx-auto max-w-[1440px]">
        <header className="flex h-14 items-center justify-between gap-2 rounded-2xl border border-border/70 bg-background/80 px-3 shadow-[0_8px_30px_rgba(0,0,0,0.06)] backdrop-blur-xl dark:bg-card/60 md:px-3 lg:gap-3 lg:px-4">
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
          <nav className="hidden min-w-0 flex-1 items-center justify-center gap-0.5 md:flex lg:gap-2">
            {isAdmin && (
              <NavPill
                label={translate("ra.page.dashboard")}
                to="/"
                isActive={currentPath === "/"}
              />
            )}
            <NavPill
              label={translate("resources.leads.name", { smart_count: 2 })}
              to="/leads"
              isActive={currentPath === "/leads"}
            />
            <NavPill
              label={translate("resources.conversations.name", {
                smart_count: 2,
              })}
              to="/conversations"
              isActive={currentPath === "/conversations"}
            />
            <NavPill
              label="Dự án"
              to="/projects"
              isActive={currentPath === "/projects"}
            />
            {isAdmin && (
              <NavPill
                label="Kiến thức"
                to="/knowledge_sources"
                isActive={currentPath === "/knowledge_sources"}
              />
            )}
            {isAdmin && (
              <NavPill
                label="Tài khoản"
                to="/users"
                isActive={currentPath === "/users"}
              />
            )}
          </nav>

          {/* Actions */}
          <div className="flex shrink-0 items-center gap-1 lg:gap-2">
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
      <Link to={ChangelogPage.path} className="flex items-center gap-2">
        <FileText />
        {translate("crm.changelog.title")}
      </Link>
    </DropdownMenuItem>
  );
};
export default Header;
