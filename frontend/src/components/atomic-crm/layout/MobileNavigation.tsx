import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { BookOpen, Home, ListTodo, Users } from "lucide-react";
import { useTranslate } from "ra-core";
import { Link, matchPath, useLocation } from "react-router";
import { useMemo } from "react";

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

  const currentPath = useMemo<string | boolean>(() => {
    if (matchPath("/", location.pathname)) return "/";
    if (matchPath("/leads/*", location.pathname)) return "/leads";
    if (matchPath("/conversations/*", location.pathname))
      return "/conversations";
    if (matchPath("/knowledge_sources/*", location.pathname))
      return "/knowledge_sources";
    return false;
  }, [location.pathname]);

  return (
    <nav
      aria-label={translate("crm.navigation.label")}
      className="fixed bottom-0 left-0 right-0 z-50 bg-secondary h-14 border-t"
      style={{
        paddingBottom: IS_PWA && IS_WEB_IOS ? 15 : undefined,
      }}
    >
      <div className="flex justify-around w-full max-w-md mx-auto h-full items-center">
        <>
          <NavigationButton
            href="/"
            Icon={Home}
            label={translate("ra.page.dashboard")}
            isActive={currentPath === "/"}
          />
          <NavigationButton
            href="/leads"
            Icon={Users}
            label={translate("resources.leads.name", {
              smart_count: 2,
            })}
            isActive={currentPath === "/leads"}
          />
          <NavigationButton
            href="/conversations"
            Icon={ListTodo}
            label={translate("resources.conversations.name", {
              smart_count: 2,
            })}
            isActive={currentPath === "/conversations"}
          />
          <NavigationButton
            href="/knowledge_sources"
            Icon={BookOpen}
            label="Kiến thức"
            isActive={currentPath === "/knowledge_sources"}
          />
        </>
      </div>
    </nav>
  );
};

const NavigationButton = ({
  href,
  Icon,
  label,
  isActive,
}: {
  href: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  label: string;
  isActive: boolean;
}) => (
  <Button
    asChild
    variant="ghost"
    className={cn(
      "flex-col gap-1 h-auto py-2 px-1 rounded-md w-16",
      isActive ? null : "text-muted-foreground",
    )}
  >
    <Link to={href}>
      <Icon className="size-6" />
      <span className="min-w-0 w-full truncate text-center text-[0.625rem] font-medium">
        {label}
      </span>
    </Link>
  </Button>
);
