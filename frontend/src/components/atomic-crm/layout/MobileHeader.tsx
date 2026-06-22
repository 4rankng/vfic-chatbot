import { Link } from "react-router";
import { ThemeModeToggle } from "@/components/admin/theme-mode-toggle";
import { UserMenu } from "@/components/admin/user-menu";

import { useConfigurationContext } from "../root/ConfigurationContext";
import { NotificationsBell } from "./topbar/NotificationsBell";

interface MobileHeaderProps {
  children?: React.ReactNode;
}

/**
 * Mobile topbar. Frosted to match the desktop glass pill. Shows the brand logo
 * when a page provides no title slot (home), otherwise the page's own
 * back/title content. Gains the theme toggle and search parity with desktop.
 */
const MobileHeader = ({ children }: MobileHeaderProps) => {
  const { title } = useConfigurationContext();

  return (
    <header className="fixed inset-x-0 top-0 z-40 flex h-16 items-center justify-between border-b border-border/70 bg-white/70 px-3 backdrop-blur-xl dark:bg-card/60">
      <div className="flex min-w-0 items-center gap-2">
        {children ?? (
          <Link to="/" className="flex h-full items-center" aria-label={title}>
            <img
              src="/light-logo.png"
              alt={title}
              className="h-7 w-auto py-1 dark:hidden"
            />
            <img
              src="/dark-logo.png"
              alt={title}
              className="hidden h-7 w-auto py-1 dark:block"
            />
          </Link>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <NotificationsBell />
        <ThemeModeToggle />
        <UserMenu />
      </div>
    </header>
  );
};

export default MobileHeader;
