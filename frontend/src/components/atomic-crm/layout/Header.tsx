import {
  BookOpen,
  Briefcase,
  ChevronDown,
  Home,
  MessageCircle,
  Sparkles,
  User,
  UserCog,
  Users,
} from "lucide-react";
import { useTranslate, useUserMenu } from "ra-core";
import { Link, matchPath, useLocation } from "react-router";
import { useMemo } from "react";
import { ThemeModeToggle } from "@/components/admin/theme-mode-toggle";
import { UserMenu } from "@/components/admin/user-menu";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { useConfigurationContext } from "../root/ConfigurationContext";
import { useRoleActions } from "../hooks/useRoleActions";
import { NavPill } from "./topbar/NavPills";
import { NotificationsBell } from "./topbar/NotificationsBell";

const isPresent = <T,>(value: T | null): value is T => value !== null;

const Header = () => {
  const { title } = useConfigurationContext();
  const location = useLocation();
  const translate = useTranslate();
  const { isAdmin } = useRoleActions();

  const currentPath = useMemo<string | false>(() => {
    if (matchPath("/", location.pathname)) return "/";
    if (matchPath("/leads/*", location.pathname)) return "/leads";
    if (matchPath("/conversations/*", location.pathname))
      return "/conversations";
    if (matchPath("/projects/*", location.pathname)) return "/projects";
    if (matchPath("/knowledge_sources/*", location.pathname))
      return "/knowledge_sources";
    if (matchPath("/users/*", location.pathname)) return "/users";
    if (matchPath("/personas/*", location.pathname)) return "/personas";
    // Unmatched secondary routes (e.g. /settings, /profile) leave no
    // pill highlighted, matching the prior behavior.
    return false;
  }, [location.pathname]);

  const dashboardItem = isAdmin
    ? {
        label: translate("ra.page.dashboard"),
        to: "/",
        isActive: currentPath === "/",
        Icon: Home,
      }
    : null;

  const coreItems = [
    dashboardItem,
    {
      label: translate("resources.leads.name", { smart_count: 2 }),
      to: "/leads",
      isActive: currentPath === "/leads",
      Icon: Users,
    },
    {
      label: translate("resources.conversations.name", { smart_count: 2 }),
      to: "/conversations",
      isActive: currentPath === "/conversations",
      Icon: MessageCircle,
    },
  ].filter(isPresent);

  const functionItems = [
    {
      label: "Dự án",
      to: "/projects",
      isActive: currentPath === "/projects",
      Icon: Briefcase,
    },
    isAdmin
      ? {
          label: "Kiến thức",
          to: "/knowledge_sources",
          isActive: currentPath === "/knowledge_sources",
          Icon: BookOpen,
        }
      : null,
    isAdmin
      ? {
          label: "Agent",
          to: "/personas",
          isActive: currentPath === "/personas",
          Icon: Sparkles,
        }
      : null,
    isAdmin
      ? {
          label: "Tài khoản",
          to: "/users",
          isActive: currentPath === "/users",
          Icon: UserCog,
        }
      : null,
  ].filter(isPresent);

  const functionMenuActive = functionItems.some((item) => item?.isActive);

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
          <nav className="hidden min-w-0 flex-1 items-center justify-center gap-0.5 md:flex 2xl:hidden">
            {coreItems.map((item) =>
              item ? (
                <NavPill
                  key={item.to}
                  label={item.label}
                  to={item.to}
                  isActive={item.isActive}
                />
              ) : null,
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  className={cn(
                    "h-9 rounded-lg px-2 text-[0.68rem] font-semibold uppercase tracking-normal lg:px-3 lg:text-xs",
                    functionMenuActive
                      ? "bg-muted/70 text-foreground shadow-sm dark:bg-muted/40"
                      : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                  )}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      functionMenuActive ? "bg-primary" : "bg-transparent",
                    )}
                  />
                  Chức năng
                  <ChevronDown className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="center"
                sideOffset={10}
                className="w-56 rounded-xl p-2 shadow-[0_16px_45px_rgba(15,23,42,0.16)]"
              >
                {functionItems.map((item) =>
                  item ? (
                    <DropdownMenuItem
                      key={item.to}
                      asChild
                      className={cn(
                        "rounded-lg px-3 py-2.5 text-sm",
                        item.isActive && "bg-accent text-accent-foreground",
                      )}
                    >
                      <Link to={item.to} className="flex items-center gap-3">
                        <item.Icon className="size-4" />
                        <span className="font-medium">{item.label}</span>
                      </Link>
                    </DropdownMenuItem>
                  ) : null,
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </nav>

          <nav className="hidden min-w-0 flex-1 items-center justify-center gap-2 2xl:flex">
            {[...coreItems, ...functionItems].map((item) => (
              <NavPill
                key={item.to}
                label={item.label}
                to={item.to}
                isActive={item.isActive}
              />
            ))}
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

export default Header;
