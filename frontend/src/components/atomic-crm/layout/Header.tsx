import { FileText, Settings, User, Users } from "lucide-react";
import { useTranslate, useUserMenu } from "ra-core";
import { Link, matchPath, useLocation } from "react-router";
import { ThemeModeToggle } from "@/components/admin/theme-mode-toggle";
import { UserMenu } from "@/components/admin/user-menu";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";

import { useConfigurationContext } from "../root/ConfigurationContext";
import { ChangelogPage } from "../misc/ChangelogPage";

const Header = () => {
  const { title } = useConfigurationContext();
  const location = useLocation();
  const translate = useTranslate();

  let currentPath: string | boolean = "/";
  if (matchPath("/", location.pathname)) {
    currentPath = "/";
  } else if (matchPath("/leads/*", location.pathname)) {
    currentPath = "/leads";
  } else if (matchPath("/conversations/*", location.pathname)) {
    currentPath = "/conversations";
  } else {
    currentPath = false;
  }

  return (
    <>
      <nav className="grow">
        <header className="bg-white dark:bg-card shadow-[0_1px_3px_rgba(0,0,0,0.05)]">
          <div className="max-w-screen-xl mx-auto px-6 md:px-8">
            <div className="flex justify-between items-stretch flex-1 h-12">
              <Link
                to="/"
                className="flex items-center text-foreground no-underline h-full"
              >
                <img
                  src="/light-logo.png"
                  className="h-full py-1 w-auto dark:hidden"
                  alt={title}
                />
                <img
                  src="/dark-logo.png"
                  className="h-full py-1 w-auto hidden dark:block"
                  alt={title}
                />
              </Link>
              <div>
                <nav className="flex">
                  <NavigationTab
                    label={translate("ra.page.dashboard")}
                    to="/"
                    isActive={currentPath === "/"}
                  />
                  <NavigationTab
                    label={translate("resources.leads.name", {
                      smart_count: 2,
                    })}
                    to="/leads"
                    isActive={currentPath === "/leads"}
                  />
                  <NavigationTab
                    label={translate("resources.conversations.name", {
                      smart_count: 2,
                    })}
                    to="/conversations"
                    isActive={currentPath === "/conversations"}
                  />
                </nav>
              </div>
              <div className="flex items-center">
                <ThemeModeToggle />
                <UserMenu />
              </div>
            </div>
          </div>
        </header>
      </nav>
    </>
  );
};

const NavigationTab = ({
  label,
  to,
  isActive,
}: {
  label: string;
  to: string;
  isActive: boolean;
}) => (
  <Link
    to={to}
    className={`flex items-center gap-2 px-5 py-2 text-xs font-semibold uppercase tracking-wider transition-all border-b-2 ${
      isActive
        ? "text-foreground border-primary"
        : "text-muted-foreground border-transparent hover:text-foreground"
    }`}
  >
    <span
      className={`w-1.5 h-1.5 rounded-full transition-all duration-300 ${
        isActive
          ? "bg-primary shadow-[0_0_8px_var(--primary)]"
          : "bg-muted-foreground/30"
      }`}
    />
    {label}
  </Link>
);

export const UsersMenu = () => {
  const translate = useTranslate();
  const userMenuContext = useUserMenu();
  if (!userMenuContext) {
    throw new Error("<UsersMenu> must be used inside <UserMenu?");
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
    throw new Error("<ProfileMenu> must be used inside <UserMenu?");
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

export const SettingsMenu = () => {
  const translate = useTranslate();
  const userMenuContext = useUserMenu();
  if (!userMenuContext) {
    throw new Error("<SettingsMenu> must be used inside <UserMenu>");
  }
  return (
    <DropdownMenuItem asChild onClick={userMenuContext.onClose}>
      <Link to="/settings" className="flex items-center gap-2">
        <Settings />
        {translate("crm.settings.title")}
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
