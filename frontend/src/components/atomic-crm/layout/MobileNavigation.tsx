import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Home, MessageCircle, Settings, UserCog } from "lucide-react";
import { useTranslate } from "ra-core";
import { Link, useLocation } from "react-router";
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
  const { count: needsAttentionCount } = useNotifications();

  const currentPath = useMemo<string | boolean>(() => {
    const path = location.pathname;
    if (path === "/") return "/";
    if (path === "/conversations" || path.startsWith("/conversations/")) {
      return "/conversations";
    }
    if (
      path === "/settings" ||
      path.startsWith("/settings/") ||
      path.startsWith("/zalo_integrations/") ||
      path === "/projects" ||
      path.startsWith("/projects/") ||
      path === "/knowledge_sources" ||
      path.startsWith("/knowledge_sources/") ||
      path === "/personas" ||
      path.startsWith("/personas/")
    ) {
      return "/settings";
    }
    if (
      path === "/profile" ||
      path === "/users" ||
      path.startsWith("/users/")
    ) {
      return "/account";
    }
    if (path === "/leads" || path.startsWith("/leads/")) return "/";
    return false;
  }, [location.pathname]);

  type NavigationItem = {
    href: string;
    Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
    label: string;
    isActive: boolean;
    badge?: number;
  };

  const visibleItems: NavigationItem[] = [
    {
      href: "/",
      Icon: Home,
      label: "Dashboard",
      isActive: currentPath === "/",
    },
    {
      href: "/conversations",
      Icon: MessageCircle,
      label: "Chat",
      isActive: currentPath === "/conversations",
      badge: needsAttentionCount,
    },
    {
      href: "/settings",
      Icon: Settings,
      label: "Settings",
      isActive: currentPath === "/settings",
    },
    {
      href: "/profile",
      Icon: UserCog,
      label: "Account",
      isActive: currentPath === "/account",
    },
  ];

  return (
    <nav
      aria-label={translate("crm.navigation.label")}
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3"
      style={{
        paddingBottom:
          IS_PWA && IS_WEB_IOS
            ? "calc(0.95rem + env(safe-area-inset-bottom))"
            : undefined,
      }}
    >
      <div
        className={cn(
          "pointer-events-auto mx-auto grid min-h-16 w-full max-w-lg items-center gap-1 rounded-[2rem] border border-border/75 bg-background/95 p-1.5 shadow-[0_16px_44px_rgba(26,34,40,0.16)] backdrop-blur-2xl",
          "grid-cols-4",
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
      "relative h-14 w-full min-w-0 flex-col gap-0.5 rounded-[1.55rem] border border-transparent bg-transparent px-1 py-1 transition-all active:scale-[0.98]",
      isActive
        ? "bg-[#def3e7] text-[#117b5f] shadow-[inset_0_0_0_1px_rgba(17,123,95,0.22)] hover:bg-[#d4efdf] hover:text-[#117b5f]"
        : "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
    )}
  >
    <Link to={href}>
      <span
        className={cn(
          "relative grid size-8 place-items-center rounded-full transition-colors",
          isActive ? "bg-[#117b5f] text-white shadow-sm" : "bg-transparent",
        )}
      >
        <Icon className="size-4 shrink-0" />
        {badge > 0 ? (
          <span className="absolute -right-2 -top-1 min-w-4 rounded-full border border-background bg-destructive px-1 py-0.5 text-[0.625rem] font-bold leading-none text-white shadow-sm">
            {badge > 99 ? "99+" : badge}
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          "max-w-full text-center text-[0.6875rem] font-semibold leading-tight break-words",
        )}
      >
        {label}
      </span>
    </Link>
  </Button>
);
