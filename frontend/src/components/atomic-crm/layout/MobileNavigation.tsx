import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  BookOpen,
  Briefcase,
  Home,
  ListTodo,
  UserCog,
  Users,
} from "lucide-react";
import { usePermissions, useTranslate } from "ra-core";
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
  const { permissions } = usePermissions();
  const isAdmin = permissions === "admin";

  const currentPath = useMemo<string | boolean>(() => {
    if (matchPath("/", location.pathname)) return "/";
    if (matchPath("/leads/*", location.pathname)) return "/leads";
    if (matchPath("/conversations/*", location.pathname))
      return "/conversations";
    if (matchPath("/knowledge_sources/*", location.pathname))
      return "/knowledge_sources";
    if (matchPath("/projects/*", location.pathname)) return "/projects";
    if (matchPath("/users/*", location.pathname)) return "/users";
    return false;
  }, [location.pathname]);

  return (
    <nav
      aria-label={translate("crm.navigation.label")}
      className="fixed bottom-0 left-0 right-0 z-50 h-14 border-t bg-secondary"
      style={{
        paddingBottom: IS_PWA && IS_WEB_IOS ? 15 : undefined,
      }}
    >
      <div
        className={cn(
          "mx-auto grid h-full w-full max-w-md items-stretch",
          isAdmin ? "grid-cols-5" : "grid-cols-3",
        )}
      >
        {isAdmin && (
          <NavigationButton
            href="/"
            Icon={Home}
            label="Tổng quan"
            isActive={currentPath === "/"}
          />
        )}
        <NavigationButton
          href="/leads"
          Icon={Users}
          label="Ứng viên"
          isActive={currentPath === "/leads"}
        />
        <NavigationButton
          href="/conversations"
          Icon={ListTodo}
          label="Tin nhắn"
          isActive={currentPath === "/conversations"}
        />
        {!isAdmin && (
          <NavigationButton
            href="/projects"
            Icon={Briefcase}
            label="Dự án"
            isActive={currentPath === "/projects"}
          />
        )}
        {isAdmin && (
          <NavigationButton
            href="/knowledge_sources"
            Icon={BookOpen}
            label="Kiến thức"
            isActive={currentPath === "/knowledge_sources"}
          />
        )}
        {isAdmin && (
          <NavigationButton
            href="/users"
            Icon={UserCog}
            label="Tài khoản"
            isActive={currentPath === "/users"}
          />
        )}
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
      "h-full w-full min-w-0 flex-col gap-1 rounded-md px-0.5 py-1.5",
      isActive ? null : "text-muted-foreground",
    )}
  >
    <Link to={href}>
      <Icon className="size-6 shrink-0" />
      <span className="max-w-full text-center text-[0.6875rem] font-medium leading-tight">
        {label}
      </span>
    </Link>
  </Button>
);
