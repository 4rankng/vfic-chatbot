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
    return false;
  }, [location.pathname]);

  const overflowItems = useMemo(
    () =>
      [
        isAdmin
          ? {
              href: "/",
              Icon: Home,
              label: translate("ra.page.dashboard"),
              isActive: currentPath === "/",
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
      ].filter(Boolean) as Array<{
        href: string;
        Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
        label: string;
        isActive: boolean;
      }>,
    [currentPath, isAdmin, translate],
  );

  const overflowActive = overflowItems.some((item) => item.isActive);

  return (
    <nav
      aria-label={translate("crm.navigation.label")}
      className="fixed bottom-0 left-0 right-0 z-50 h-24 border-t border-border/70 bg-background/95 px-4 pb-2 pt-3 shadow-[0_-10px_30px_rgba(0,0,0,0.08)] backdrop-blur-xl dark:bg-card/95"
      style={{
        paddingBottom: IS_PWA && IS_WEB_IOS ? 15 : undefined,
      }}
    >
      <div className="relative mx-auto grid h-full w-full max-w-md grid-cols-[1fr_1fr_5rem_1fr] items-end gap-1.5">
        <NavigationButton
          href="/leads"
          Icon={Users}
          label="Ứng viên"
          isActive={currentPath === "/leads"}
        />
        <NavigationButton
          href="/projects"
          Icon={Briefcase}
          label="Dự án"
          isActive={currentPath === "/projects"}
        />
        <NavigationButton
          href="/conversations"
          Icon={MessageCircle}
          label="Chat"
          isActive={currentPath === "/conversations"}
          cta
          badge={needsAttentionCount}
        />
        {overflowItems.length > 0 ? (
          <div className="col-start-4">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Mở thêm chức năng"
                  className={cn(
                    "relative h-14 w-full min-w-0 flex-col gap-1 rounded-xl px-2 py-1.5",
                    overflowActive
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  <MoreHorizontal className="size-5 shrink-0" />
                  <span className="max-w-full text-center text-[0.6875rem] font-medium leading-tight">
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
  cta = false,
  badge = 0,
}: {
  href: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  label: string;
  isActive: boolean;
  cta?: boolean;
  badge?: number;
}) => (
  <Button
    asChild
    variant="ghost"
    className={cn(
      "relative h-14 w-full min-w-0 flex-col gap-1 rounded-xl px-2 py-1.5",
      cta &&
        "absolute bottom-2 left-1/2 h-20 w-20 -translate-x-1/2 rounded-3xl bg-primary text-primary-foreground shadow-xl shadow-primary/30 hover:bg-primary/90 hover:text-primary-foreground",
      !cta && (isActive ? "bg-muted text-foreground" : "text-muted-foreground"),
    )}
  >
    <Link to={href}>
      <span className="relative">
        <Icon className={cn("shrink-0", cta ? "size-8" : "size-5")} />
        {cta && badge > 0 ? (
          <span className="absolute -right-3 -top-2 min-w-5 rounded-full border border-primary-foreground/70 bg-destructive px-1.5 py-0.5 text-[0.625rem] font-bold leading-none text-white shadow-sm">
            {badge > 99 ? "99+" : badge}
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          "max-w-full text-center font-medium leading-tight",
          cta ? "text-xs font-semibold" : "text-[0.6875rem]",
        )}
      >
        {label}
      </span>
    </Link>
  </Button>
);
