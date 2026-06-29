import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import {
  BookOpen,
  Briefcase,
  Home,
  MessageCircle,
  MoreHorizontal,
  UserCog,
  Users,
} from "lucide-react";
import { usePermissions, useTranslate } from "ra-core";
import { Link, matchPath, useLocation } from "react-router";
import { useMemo } from "react";
import { useNotifications } from "./topbar/useNotifications";

// Static per-session: display-mode and UA do not change without a reload.
const IS_PWA =
  typeof window !== "undefined" &&
  window.matchMedia("(display-mode: standalone)").matches;
const IS_WEB_IOS =
  typeof window !== "undefined" &&
  /iPad|iPod|iPhone/.test(window.navigator.userAgent);

export const MobileNavigation = () => {
  const location = useLocation();
  const translate = useTranslate();
  const { permissions } = usePermissions();
  const { count: needsAttentionCount } = useNotifications();
  const isAdmin = permissions === "admin";

  const currentPath = useMemo<string | boolean>(() => {
    if (matchPath("/", location.pathname)) return "/";
    if (matchPath("/leads/*", location.pathname)) return "/leads";
    if (matchPath("/conversations/*", location.pathname))
      return "/conversations";
    if (matchPath("/projects/*", location.pathname)) return "/projects";
    if (matchPath("/knowledge_sources/*", location.pathname))
      return "/knowledge_sources";
    if (matchPath("/users/*", location.pathname)) return "/users";
    if (matchPath("/profile", location.pathname)) return "/profile";
    return false;
  }, [location.pathname]);

  type NavigationItem = {
    href: string;
    Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
    label: string;
    isActive: boolean;
    badge?: number;
  };

  const overflowItems = useMemo(
    () =>
      [
        isAdmin
          ? {
              href: "/projects",
              Icon: Briefcase,
              label: "Dự án",
              isActive: currentPath === "/projects",
            }
          : null,
        isAdmin
          ? {
              href: "/knowledge_sources",
              Icon: BookOpen,
              label: "Kiến thức",
              isActive: currentPath === "/knowledge_sources",
            }
          : null,
        isAdmin
          ? {
              href: "/users",
              Icon: UserCog,
              label: "Tài khoản",
              isActive: currentPath === "/users",
            }
          : null,
      ].filter(Boolean) as NavigationItem[],
    [currentPath, isAdmin],
  );

  const overflowActive = overflowItems.some((item) => item.isActive);
  const visibleItems: NavigationItem[] = isAdmin
    ? [
        {
          href: "/",
          Icon: Home,
          label: "Dashboard",
          isActive: currentPath === "/",
        },
        {
          href: "/leads",
          Icon: Users,
          label: "Ứng viên",
          isActive: currentPath === "/leads",
        },
        {
          href: "/conversations",
          Icon: MessageCircle,
          label: "Chat",
          isActive: currentPath === "/conversations",
          badge: needsAttentionCount,
        },
      ]
    : [
        {
          href: "/leads",
          Icon: Users,
          label: "Ứng viên",
          isActive: currentPath === "/leads",
        },
        {
          href: "/conversations",
          Icon: MessageCircle,
          label: "Chat",
          isActive: currentPath === "/conversations",
          badge: needsAttentionCount,
        },
        {
          href: "/projects",
          Icon: Briefcase,
          label: "Dự án",
          isActive: currentPath === "/projects",
        },
        {
          href: "/profile",
          Icon: UserCog,
          label: "Tài khoản",
          isActive: currentPath === "/profile",
        },
      ];

  return (
    <nav
      aria-label={translate("crm.navigation.label")}
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-border/70 bg-background/94 px-3 pb-1 pt-1 shadow-[0_-8px_24px_rgba(26,34,40,0.08)] backdrop-blur-xl dark:bg-card/92"
      style={{
        paddingBottom: IS_PWA && IS_WEB_IOS ? 15 : undefined,
      }}
    >
      <div
        className={cn(
          "mx-auto grid min-h-11 w-full max-w-md items-center gap-1",
          visibleItems.length + (overflowItems.length > 0 ? 1 : 0) === 4
            ? "grid-cols-4"
            : "grid-cols-3",
        )}
      >
        {visibleItems.map(({ href, Icon, label, isActive, badge }) => (
          <NavigationButton
            key={href}
            href={href}
            Icon={Icon}
            label={label}
            isActive={isActive}
            badge={badge}
          />
        ))}
        {overflowItems.length > 0 ? (
          <div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Mở thêm chức năng"
                  className={cn(
                    "relative h-11 w-full min-w-0 flex-col gap-0.5 rounded-none border-t-2 border-transparent bg-transparent px-1 py-0.5 transition-colors",
                    overflowActive
                      ? "border-primary text-primary hover:bg-transparent hover:text-primary"
                      : "text-muted-foreground hover:bg-transparent hover:text-foreground",
                  )}
                >
                  <MoreHorizontal className="size-4 shrink-0" />
                  <span className="max-w-full truncate text-center text-[0.625rem] font-semibold leading-tight">
                    Thêm
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                side="top"
                sideOffset={12}
                className="mb-1 w-56 rounded-xl p-2 shadow-[0_16px_45px_rgba(15,23,42,0.18)]"
              >
                {overflowItems.map(({ href, Icon, label, isActive }) => (
                  <DropdownMenuItem
                    key={href}
                    asChild
                    className={cn(
                      "rounded-lg px-3 py-2.5 text-sm",
                      isActive && "bg-accent text-accent-foreground",
                    )}
                  >
                    <Link to={href} className="flex items-center gap-3">
                      <Icon className="size-4" />
                      <span className="font-medium">{label}</span>
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null}
      </div>
    </nav>
  );
};

const NavigationButton = ({
  href,
  Icon,
  label,
  isActive,
  badge = 0,
}: {
  href: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  label: string;
  isActive: boolean;
  badge?: number;
}) => (
  <Button
    asChild
    variant="ghost"
    className={cn(
      "relative h-11 w-full min-w-0 flex-col gap-0.5 rounded-none border-t-2 border-transparent bg-transparent px-1 py-0.5 transition-colors",
      isActive
        ? "border-primary text-primary hover:bg-transparent hover:text-primary"
        : "text-muted-foreground hover:bg-transparent hover:text-foreground",
    )}
  >
    <Link to={href}>
      <span className="relative">
        <Icon className="size-4 shrink-0" />
        {badge > 0 ? (
          <span className="absolute -right-3 -top-2 min-w-4 rounded-full border border-background bg-destructive px-1 py-0.5 text-[0.5625rem] font-bold leading-none text-white shadow-sm">
            {badge > 99 ? "99+" : badge}
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          "max-w-full truncate text-center text-[0.625rem] font-semibold leading-tight",
        )}
      >
        {label}
      </span>
    </Link>
  </Button>
);
