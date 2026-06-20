import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Home, ListTodo, Plus, Settings, Users } from "lucide-react";
import { useTranslate } from "ra-core";
import { Link, matchPath, useLocation } from "react-router";

export const MobileNavigation = () => {
  const location = useLocation();
  const translate = useTranslate();

  let currentPath: string | boolean = "/";
  if (matchPath("/", location.pathname)) {
    currentPath = "/";
  } else if (matchPath("/leads/*", location.pathname)) {
    currentPath = "/leads";
  } else if (matchPath("/conversations/*", location.pathname)) {
    currentPath = "/conversations";
  } else if (matchPath("/profiles/*", location.pathname)) {
    currentPath = "/profiles";
  } else {
    currentPath = false;
  }

  const isPwa = window.matchMedia("(display-mode: standalone)").matches;
  const isWebiOS = /iPad|iPod|iPhone/.test(window.navigator.userAgent);

  return (
    <nav
      aria-label={translate("crm.navigation.label")}
      className="fixed bottom-0 left-0 right-0 z-50 bg-secondary h-14 border-t"
      style={{
        paddingBottom: isPwa && isWebiOS ? 15 : undefined,
        height: "calc(var(--spacing)) * 6" + (isPwa && isWebiOS ? " + 15px" : ""),
      }}
    >
      <div className="flex justify-center h-full items-center">
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
          <CreateButton />
          <NavigationButton
            href="/conversations"
            Icon={ListTodo}
            label={translate("resources.conversations.name", { smart_count: 2 })}
            isActive={currentPath === "/conversations"}
          />
          <NavigationButton
            href="/profiles"
            Icon={Settings}
            label="Profiles"
            isActive={currentPath === "/profiles"}
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
      <span className="text-[0.6rem] font-medium">{label}</span>
    </Link>
  </Button>
);

const CreateButton = () => {
  const translate = useTranslate();

  return (
    <Button
      asChild
      variant="default"
      size="icon"
      className="h-16 w-16 rounded-full -mt-8 mx-2 shadow-lg hover:shadow-xl transition-all"
      aria-label={translate("ra.action.create")}
    >
      <Link to="/leads/create">
        <Plus className="size-10" />
      </Link>
    </Button>
  );
};
