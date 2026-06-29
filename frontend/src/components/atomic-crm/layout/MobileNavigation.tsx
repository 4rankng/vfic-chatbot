import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Briefcase, MessageCircle, Users } from "lucide-react";
import { useTranslate } from "ra-core";
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
  const { count: needsAttentionCount } = useNotifications();

  const currentPath = useMemo<string | boolean>(() => {
    if (matchPath("/", location.pathname)) return "/";
    if (matchPath("/leads/*", location.pathname)) return "/leads";
    if (matchPath("/conversations/*", location.pathname))
      return "/conversations";
    if (matchPath("/projects/*", location.pathname)) return "/projects";
    return false;
  }, [location.pathname]);

  return (
    <nav
      aria-label={translate("crm.navigation.label")}
      className="fixed bottom-0 left-0 right-0 z-50 h-20 border-t border-border/70 bg-background/95 px-4 pb-2 pt-2 shadow-[0_-10px_30px_rgba(0,0,0,0.08)] backdrop-blur-xl dark:bg-card/95"
      style={{
        paddingBottom: IS_PWA && IS_WEB_IOS ? 15 : undefined,
      }}
    >
      <div className="mx-auto grid h-full w-full max-w-md grid-cols-[1fr_1.35fr_1fr] items-end gap-2">
        <NavigationButton
          href="/leads"
          Icon={Users}
          label="Ứng viên"
          isActive={currentPath === "/leads"}
        />
        <NavigationButton
          href="/conversations"
          Icon={MessageCircle}
          label="Zalo chat"
          isActive={currentPath === "/conversations"}
          cta
          badge={needsAttentionCount}
        />
        <NavigationButton
          href="/projects"
          Icon={Briefcase}
          label="Dự án"
          isActive={currentPath === "/projects"}
        />
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
        "h-16 -translate-y-2 rounded-2xl bg-primary text-primary-foreground shadow-lg shadow-primary/25 hover:bg-primary/90 hover:text-primary-foreground",
      !cta && (isActive ? "bg-muted text-foreground" : "text-muted-foreground"),
    )}
  >
    <Link to={href}>
      <span className="relative">
        <Icon className={cn("shrink-0", cta ? "size-7" : "size-5")} />
        {cta && badge > 0 ? (
          <span className="absolute -right-3 -top-2 min-w-5 rounded-full border border-primary-foreground/70 bg-destructive px-1.5 py-0.5 text-[0.625rem] font-bold leading-none text-white">
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
